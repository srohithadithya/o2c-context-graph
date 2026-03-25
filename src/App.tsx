import ForceGraph2D, { ForceGraphMethods } from "react-force-graph-2d";
import type { RefObject } from "react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type NodeKind = "order" | "payment" | "delivery" | "billing" | "master" | "entity";

interface GraphNode {
  id: string;
  type: NodeKind;
  label: string;
  table?: string;
  group?: string; // added group as asked
}

interface GraphLink {
  source: string;
  target: string;
  label?: string;
}

interface GraphPayload {
  nodes: GraphNode[];
  links: GraphLink[];
  warning?: string;
}

interface ChatApiResponse {
  response: string;
  sql_query: string;
  nodes_to_highlight: string[];
}

const TYPE_COLOR: Record<string, string> = {
  order: "#3b82f6",     // blue
  payment: "#10b981",   // emerald
  delivery: "#ef4444",  // red
  billing: "#a855f7",   // purple
  master: "#f59e0b",    // amber
  entity: "#64748b",    // slate fallback
};

const CORE_TYPES = [
  { id: "order", label: "Orders", color: "bg-blue-500" },
  { id: "delivery", label: "Deliveries", color: "bg-red-500" },
  { id: "billing", label: "Billing", color: "bg-purple-500" },
  { id: "payment", label: "Payments", color: "bg-emerald-500" },
];

const CONTEXT_TYPES = [
  { id: "master", label: "Master Data", color: "bg-amber-500" },
  { id: "entity", label: "Other", color: "bg-slate-500" },
];

type ChatMessage =
  | { role: "user"; content: string }
  | {
      role: "assistant";
      content: string;
      sql_query?: string;
    }
  | {
      role: "system";
      content: string;
    };

function useResizeObserver(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 600, height: 500 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const { clientWidth, clientHeight } = el;
      if (clientWidth > 0 && clientHeight > 0) {
        setSize({ width: clientWidth, height: clientHeight });
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

function renderFormattedText(text: string) {
  return text.split("\n").map((line, i) => {
    let safeLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    let html = safeLine.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`([^`]+)`/g, '<code class="bg-black/10 px-1 py-0.5 rounded text-[11px] font-mono">$1</code>');
    
    if (html.trim().startsWith('- ') || html.trim().startsWith('* ')) {
      return <li key={i} className="ml-5 mb-1 list-disc" dangerouslySetInnerHTML={{ __html: html.trim().substring(2) }} />;
    }
    const match = html.trim().match(/^(\d+\.)\s(.*)/);
    if (match) {
      return <li key={i} className="ml-5 mb-1 list-decimal" dangerouslySetInnerHTML={{ __html: match[2] }} />;
    }
    if (html.trim() === "") return <div key={i} className="h-2" />;
    return <p key={i} className="mb-1 last:mb-0" dangerouslySetInnerHTML={{ __html: html }} />;
  });
}

export default function App() {
  const graphWrapRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const graphSize = useResizeObserver(graphWrapRef);

  const [rawNodes, setRawNodes] = useState<GraphNode[]>([]);
  const [rawLinks, setRawLinks] = useState<GraphLink[]>([]);
  const [graphWarning, setGraphWarning] = useState<string | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [highlightIds, setHighlightIds] = useState<string[]>([]);
  
  const [loadedMetadata, setLoadedMetadata] = useState<any>(null);
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [visibleTypes, setVisibleTypes] = useState<Set<string>>(
    new Set(["order", "payment", "delivery", "billing"]) // Master & Entity hidden by default for simplicity!
  );

  const neighbors = useMemo(() => {
    if (!hoverNode) return { nodes: new Set<string>(), links: new Set<string>() };
    const n = new Set<string>();
    const l = new Set<string>();
    n.add(hoverNode);
    for (const link of rawLinks) {
      const src = typeof link.source === "object" ? (link.source as any).id : link.source;
      const tgt = typeof link.target === "object" ? (link.target as any).id : link.target;
      if (src === hoverNode || tgt === hoverNode) {
        n.add(src);
        n.add(tgt);
        l.add(`${src}-${tgt}`);
      }
    }
    return { nodes: n, links: l };
  }, [hoverNode, rawLinks]);

  const graphData = useMemo(() => {
    const filteredNodes = rawNodes.filter(n => visibleTypes.has(n.group || n.type));
    const validIds = new Set(filteredNodes.map(n => n.id));
    const filteredLinks = rawLinks.filter(l => {
      const srcId = typeof l.source === 'object' ? (l.source as any).id : l.source;
      const tgtId = typeof l.target === 'object' ? (l.target as any).id : l.target;
      return validIds.has(srcId) && validIds.has(tgtId);
    });
    return {
      nodes: filteredNodes.map(n => ({ ...n })),
      links: filteredLinks.map(l => ({ ...l })),
    };
  }, [rawNodes, rawLinks, visibleTypes]);

  const highlightSet = useMemo(
    () => new Set(highlightIds),
    [highlightIds],
  );

  const nodeCanvasObject = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const id = String(node.id);
    const isHighlighted = highlightSet.has(id);
    const isHovered = hoverNode === id;
    const isNeighbor = hoverNode ? neighbors.nodes.has(id) : true;

    const t = node.group || node.type;
    const baseColor = TYPE_COLOR[t] || TYPE_COLOR.entity;
    const color = (hoverNode && !isNeighbor) ? "rgba(203, 213, 225, 0.4)" : baseColor;
    
    const size = isHighlighted || isHovered ? 6 : 4;
    
    ctx.beginPath();
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI, false);
    ctx.fillStyle = color;
    ctx.fill();
    
    if (isHighlighted || isHovered) {
      ctx.lineWidth = 1.5 / globalScale;
      ctx.strokeStyle = '#334155';
      ctx.stroke();
    }
    
    if (isHovered || isHighlighted) {
      const fontSize = Math.max(12 / globalScale, 2);
      ctx.font = `500 ${fontSize}px Sans-Serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = isHovered ? '#0f172a' : '#334155';
      
      // Soft background to text to make it readable in dense graphs
      const textWidth = ctx.measureText(node.label).width;
      const bky = node.y + size + Math.max(2 / globalScale, 1);
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      ctx.fillRect(node.x - textWidth/2 - 2/globalScale, bky - 1/globalScale, textWidth + 4/globalScale, fontSize + 2/globalScale);
      
      ctx.fillStyle = isHovered ? '#0f172a' : '#334155';
      ctx.fillText(node.label, node.x, bky);
    }
  }, [highlightSet, hoverNode, neighbors]);

  const onNodeClick = useCallback((node: GraphNode) => {
    (async () => {
      try {
        const r = await fetch(`/api/node/${encodeURIComponent(node.id)}`);
        if (r.ok) {
          const details = await r.json();
          // We can set a local dialog/modal or system message
          setLoadedMetadata(details);
          setInput(`Analyze details for ${node.id}`);
        } else {
          setInput(`Analyze ${node.id}`);
        }
      } catch (e) {
        setInput(`Analyze ${node.id}`);
      }
    })();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setGraphLoading(true);
      try {
        const r = await fetch("/api/graph/data");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as GraphPayload;
        if (cancelled) return;
        setRawNodes(data.nodes ?? []);
        setRawLinks(data.links ?? []);
        setGraphWarning(data.warning ?? null);
      } catch {
        if (!cancelled) {
          setGraphWarning("Could not load graph data.");
          setRawNodes([]);
          setRawLinks([]);
        }
      } finally {
        if (!cancelled) setGraphLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Improve visual compactness to prevent "very long" stringy graphs
    if (fgRef.current && graphData.nodes.length > 0) {
      const charge = fgRef.current.d3Force("charge");
      if (charge) charge.distanceMax(300);
      const center = fgRef.current.d3Force("center");
      if (center) center.strength(0.04);
    }
  }, [graphData]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setSending(true);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");

    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const payload = (await r.json()) as ChatApiResponse & { detail?: string };

      if (!r.ok) {
        const err =
          typeof payload.detail === "string"
            ? payload.detail
            : `Request failed (${r.status})`;
        setMessages((m) => [
          ...m,
          { role: "assistant", content: err, sql_query: "" },
        ]);
        return;
      }

      const highlights = payload.nodes_to_highlight ?? [];
      setHighlightIds(highlights);
      if (highlights.length > 0) {
        const hTypes = new Set(rawNodes.filter(n => highlights.includes(String(n.id))).map(n => n.group || n.type));
        if (hTypes.size > 0) {
          setVisibleTypes(prev => {
            const next = new Set(prev);
            hTypes.forEach(t => next.add(t as string));
            return next;
          });
        }
      }
      
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: payload.response,
          sql_query: payload.sql_query,
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content:
            e instanceof Error ? e.message : "Network error calling Dodge AI.",
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex h-screen min-h-0 flex-col bg-white text-slate-900 font-sans">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Order-to-Cash
          </p>
          <h1 className="text-lg font-semibold tracking-tight text-slate-800">
            Context Graph
          </h1>
        </div>
        <div className="flex gap-4 items-center text-xs text-slate-500">
          <div>
            <span className="font-mono text-slate-600 font-medium">{rawNodes.length}</span> nodes
            <span className="mx-2 text-slate-300">·</span>
            <span className="font-mono text-slate-600 font-medium">{rawLinks.length}</span> links
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left: force graph */}
        <section className="relative flex min-w-0 flex-1 flex-col border-r border-slate-200 bg-white shadow-lg z-10">
          <div className="flex flex-col gap-2 relative z-10 w-full px-5 py-3 border-b border-slate-200 bg-white/90 backdrop-blur shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-800 tracking-wider uppercase">
                Interactive Map
              </span>
              <button 
                onClick={() => fgRef.current?.zoomToFit(400, 20)}
                className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-600 bg-white border border-slate-300 rounded hover:bg-slate-50 transition-colors shadow-sm"
              >
                Zoom to Fit
              </button>
            </div>
            
            <div className="flex items-center justify-between mt-1">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold">
                <span className="text-slate-400 mr-1 hidden sm:inline-block">Core Flow:</span>
                {CORE_TYPES.map(t => {
                  const active = visibleTypes.has(t.id);
                  return (
                    <button
                      key={t.id}
                      onClick={() => {
                        const next = new Set(visibleTypes);
                        if (next.has(t.id)) next.delete(t.id);
                        else next.add(t.id);
                        setVisibleTypes(next);
                      }}
                      className={`flex items-center gap-1.5 px-2 py-1 rounded transition-all ${
                        active 
                          ? "text-slate-800 bg-slate-100 border border-slate-300 shadow-sm" 
                          : "text-slate-400 bg-transparent hover:bg-slate-50 border border-transparent"
                      }`}
                    >
                      <span className={`h-2 w-2 rounded-full ${t.color} ${active ? 'shadow-sm' : 'opacity-40 grayscale'}`} />
                      {t.label}
                    </button>
                  );
                })}
              </div>
              
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold border-l border-slate-200 pl-3">
                <span className="text-amber-600/70 mr-1 hidden sm:inline-block">Extended Context:</span>
                {CONTEXT_TYPES.map(t => {
                  const active = visibleTypes.has(t.id);
                  return (
                    <button
                      key={t.id}
                      onClick={() => {
                        const next = new Set(visibleTypes);
                        if (next.has(t.id)) next.delete(t.id);
                        else next.add(t.id);
                        setVisibleTypes(next);
                      }}
                      className={`flex items-center gap-1.5 px-2 py-1 rounded transition-all ${
                        active 
                          ? "text-slate-800 bg-amber-50 border border-amber-200 shadow-sm" 
                          : "text-slate-400 bg-transparent hover:bg-slate-50 border border-transparent"
                      }`}
                    >
                      <span className={`h-2 w-2 rounded-full ${t.color} ${active ? 'shadow-sm' : 'opacity-40 grayscale'}`} />
                      {t.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div ref={graphWrapRef} className="relative min-h-0 flex-1 w-full">
            {graphLoading ? (
              <div className="flex h-full items-center justify-center text-sm font-medium text-slate-400">
                <Spinner />
                <span className="ml-2">Loading graph…</span>
              </div>
            ) : (
              <ForceGraph2D
                ref={fgRef as any}
                width={graphSize.width}
                height={graphSize.height}
                graphData={graphData}
                nodeId="id"
                nodeCanvasObject={nodeCanvasObject}
                linkColor={(link: any) => {
                  const src = typeof link.source === 'object' ? link.source.id : link.source;
                  const tgt = typeof link.target === 'object' ? link.target.id : link.target;
                  if (hoverNode) {
                    if (neighbors.links.has(`${src}-${tgt}`)) return "rgba(99, 102, 241, 0.9)";
                    return "rgba(226, 232, 240, 0.1)";
                  }
                  return "rgba(148, 163, 184, 0.35)";
                }}
                linkWidth={(link: any) => {
                  const src = typeof link.source === 'object' ? link.source.id : link.source;
                  const tgt = typeof link.target === 'object' ? link.target.id : link.target;
                  if (hoverNode && neighbors.links.has(`${src}-${tgt}`)) return 2;
                  return 0.8;
                }}
                linkDirectionalParticles={1}
                linkDirectionalParticleWidth={(link: any) => {
                  const src = typeof link.source === 'object' ? link.source.id : link.source;
                  const tgt = typeof link.target === 'object' ? link.target.id : link.target;
                  return (hoverNode && neighbors.links.has(`${src}-${tgt}`)) ? 3 : 0;
                }}
                backgroundColor="#ffffff"
                cooldownTicks={120}
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.35}
                enableNodeDrag
                onNodeClick={onNodeClick}
                onNodeHover={(node: any) => setHoverNode(node ? String(node.id) : null)}
              />
            )}
          </div>

          {graphWarning && (
            <p className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs font-medium text-amber-800">
              {graphWarning}
            </p>
          )}

          {loadedMetadata && (
            <div className="absolute bottom-4 left-4 max-w-sm w-full bg-white border border-slate-200 shadow-xl rounded-xl p-4 text-xs z-20">
              <div className="flex justify-between items-center mb-3">
                <h3 className="font-bold text-slate-800 tracking-tight">O2C Document Record</h3>
                <button onClick={() => setLoadedMetadata(null)} className="text-slate-400 hover:text-red-500 font-bold px-2 py-0.5 rounded hover:bg-red-50 transition-colors">✕</button>
              </div>
              <p className="text-[10px] uppercase font-bold tracking-wider text-indigo-500 mb-2 truncate" title={loadedMetadata.id}>
                ID: {String(loadedMetadata.id).split(":").pop()}
              </p>
              <div className="bg-slate-50 border border-slate-100 rounded-lg p-2 max-h-56 overflow-y-auto space-y-0.5 shadow-inner">
                {Object.entries(loadedMetadata.data || {}).map(([k, v]) => {
                  const val = v === null || v === "" || v === undefined ? "-" : typeof v === 'object' ? "{ ... }" : String(v);
                  return (
                    <div key={k} className="flex justify-between items-start py-1.5 border-b border-slate-200/60 last:border-0 hover:bg-white rounded transition-colors px-1.5">
                      <span className="font-semibold text-[10px] text-slate-600 capitalize mr-4 shrink-0 mt-0.5">
                        {k.replace(/_/g, " ")}
                      </span>
                      <span className="font-mono text-[9.5px] font-medium text-slate-800 bg-slate-200/60 px-1.5 py-0.5 rounded text-right break-words max-w-[60%]">
                        {val}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        {/* Right: Dodge AI */}
        <aside className="flex w-full max-w-md shrink-0 flex-col bg-slate-50 z-0">
          <div className="border-b border-slate-200 px-5 py-4 bg-white flex justify-between items-start">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-500">
                Assistant
              </p>
              <h2 className="mt-1 text-xl font-bold tracking-tight text-slate-900">
                Dodge AI
              </h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                Ask in natural language. Answers use live SQL on{" "}
                <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-600 font-medium border border-slate-200">
                  o2c_context.db
                </code>{" "}
                and may highlight nodes in the graph.
              </p>
            </div>
            <button 
              onClick={() => { setMessages([]); setHighlightIds([]); setLoadedMetadata(null); }}
              className="text-xs font-medium text-slate-500 hover:text-red-500 transition-colors bg-slate-100 hover:bg-red-50 px-2 py-1 rounded"
            >
              Clear Chat
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-4 pb-4 pt-4">
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-inner p-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 space-y-3">
                  <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-300">
                    <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                  </div>
                  <p className="text-sm font-medium">Try: “How many sales order headers do we have?”</p>
                  <p className="text-xs">Or click a graph node to load metadata and analyze it.</p>
                </div>
              )}
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed shadow-sm ${
                      msg.role === "user"
                        ? "bg-blue-600 text-white rounded-br-sm"
                        : "bg-slate-200 text-slate-900 rounded-bl-sm"
                    }`}
                  >
                    <div className="text-[13px] leading-relaxed">
                      {renderFormattedText(msg.content)}
                    </div>
                    {msg.role === "assistant" && msg.sql_query && (
                      <details className="mt-2 text-slate-500 group">
                        <summary className="cursor-pointer text-[10px] flex items-center gap-1 opacity-70 hover:opacity-100 transition-opacity list-none pt-2 border-t border-slate-300">
                          <svg className="w-3 h-3 group-open:rotate-90 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                          Technical Details
                        </summary>
                        <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-800 p-2 font-mono text-[10px] leading-tight text-emerald-400 shadow-inner">
                          {msg.sql_query}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-slate-200 px-4 py-3 text-[13px] text-slate-900 shadow-sm flex items-center gap-2">
                    <div className="flex space-x-1 items-center mr-1">
                      <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-bounce"></div>
                      <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                      <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: "0.4s" }}></div>
                    </div>
                    <span className="font-medium text-slate-500 ml-1">Thinking...</span>
                  </div>
                </div>
              )}
            </div>

            <div className="shrink-0 space-y-2 mt-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendMessage();
                  }
                }}
                rows={3}
                placeholder="Ask Dodge AI…"
                className="w-full resize-none rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 shadow-sm transition-all"
              />
              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  disabled={sending || !input.trim()}
                  onClick={() => void sendMessage()}
                  className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md transition-all hover:bg-blue-700 hover:shadow-lg disabled:opacity-50 disabled:shadow-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                >
                  Send
                </button>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Spinner({ className }: { className?: string }) {
  return (
    <div className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-solid border-current border-e-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite] ${className || 'text-indigo-600'}`} role="status">
      <span className="!absolute !-m-px !h-px !w-px !overflow-hidden !whitespace-nowrap !border-0 !p-0 ![clip:rect(0,0,0,0)]">Loading...</span>
    </div>
  );
}
