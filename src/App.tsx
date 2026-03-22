import ForceGraph2D from "react-force-graph-2d";
import type { RefObject } from "react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type NodeKind = "order" | "payment" | "delivery";

interface GraphNode {
  id: string;
  type: NodeKind;
  label: string;
  table?: string;
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

const TYPE_COLOR: Record<NodeKind, string> = {
  order: "#3b82f6",
  payment: "#22c55e",
  delivery: "#ef4444",
};

type ChatMessage =
  | { role: "user"; content: string }
  | {
      role: "assistant";
      content: string;
      sql_query?: string;
    };

function useResizeObserver(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 600, height: 500 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const measure = () => {
      const { clientWidth, clientHeight } = el;
      if (clientWidth > 0 && clientHeight > 0) {
        setSize({ width: clientWidth, clientHeight });
      }
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);

  return size;
}

export default function App() {
  const graphWrapRef = useRef<HTMLDivElement>(null);
  const graphSize = useResizeObserver(graphWrapRef);

  const [rawNodes, setRawNodes] = useState<GraphNode[]>([]);
  const [rawLinks, setRawLinks] = useState<GraphLink[]>([]);
  const [graphWarning, setGraphWarning] = useState<string | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [highlightIds, setHighlightIds] = useState<string[]>([]);

  const graphData = useMemo(
    () => ({
      nodes: rawNodes.map((n) => ({ ...n })),
      links: rawLinks.map((l) => ({ ...l })),
    }),
    [rawNodes, rawLinks],
  );

  const highlightSet = useMemo(
    () => new Set(highlightIds),
    [highlightIds],
  );

  const nodeColor = useCallback(
    (node: GraphNode) => {
      const id = String(node.id);
      if (highlightSet.has(id)) return "#facc15";
      const t = node.type in TYPE_COLOR ? node.type : "order";
      return TYPE_COLOR[t];
    },
    [highlightSet],
  );

  const nodeVal = useCallback(
    (node: GraphNode) => (highlightSet.has(String(node.id)) ? 5 : 2),
    [highlightSet],
  );

  const onNodeClick = useCallback((node: GraphNode) => {
    setInput(`Analyze ${node.id}`);
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

      setHighlightIds(payload.nodes_to_highlight ?? []);
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
    <div className="flex h-screen min-h-0 flex-col bg-[#0b0f14] text-slate-100">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-800/90 bg-[#0d1117] px-5 py-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Order-to-Cash
          </p>
          <h1 className="text-lg font-semibold tracking-tight text-slate-100">
            Context Graph
          </h1>
        </div>
        <div className="text-right text-xs text-slate-500">
          <span className="font-mono text-slate-400">
            {rawNodes.length} nodes
          </span>
          <span className="mx-2 text-slate-700">·</span>
          <span className="font-mono text-slate-400">
            {rawLinks.length} links
          </span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left: force graph */}
        <section className="relative flex min-w-0 flex-1 flex-col border-r border-slate-800/90 bg-[#070a0e]">
          <div className="flex items-center justify-between border-b border-slate-800/80 px-4 py-2">
            <span className="text-xs font-medium text-slate-400">
              O2C graph
            </span>
            <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-blue-500" />
                Orders
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                Payments
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                Deliveries
              </span>
            </div>
          </div>

          <div
            ref={graphWrapRef}
            className="relative min-h-0 flex-1 w-full"
          >
            {graphLoading ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Loading graph…
              </div>
            ) : (
              <ForceGraph2D
                width={graphSize.width}
                height={graphSize.height}
                graphData={graphData}
                nodeId="id"
                nodeLabel="label"
                nodeColor={nodeColor}
                nodeVal={nodeVal}
                linkColor={() => "rgba(148, 163, 184, 0.35)"}
                linkWidth={0.6}
                backgroundColor="#070a0e"
                cooldownTicks={120}
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.35}
                enableNodeDrag
                onNodeClick={onNodeClick}
              />
            )}
          </div>

          {graphWarning && (
            <p className="border-t border-amber-900/40 bg-amber-950/30 px-4 py-2 text-xs text-amber-200/90">
              {graphWarning}
            </p>
          )}
        </section>

        {/* Right: Dodge AI */}
        <aside className="flex w-full max-w-md shrink-0 flex-col border-l border-slate-800/90 bg-[#0d1117]">
          <div className="border-b border-slate-800/90 px-5 py-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-400/90">
              Assistant
            </p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-white">
              Dodge AI
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              Ask in natural language. Answers use live SQL on{" "}
              <code className="rounded bg-slate-800/80 px-1 py-0.5 font-mono text-[11px] text-slate-300">
                o2c_context.db
              </code>{" "}
              and may highlight nodes in the graph.
            </p>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-4 pb-4 pt-2">
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto rounded-xl border border-slate-800/80 bg-[#0b0f14] p-4">
              {messages.length === 0 && (
                <p className="text-sm leading-relaxed text-slate-500">
                  Try: “How many sales order headers do we have?” or click a
                  graph node to analyze it.
                </p>
              )}
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={
                    msg.role === "user"
                      ? "ml-6 rounded-lg border border-slate-700/80 bg-slate-800/50 px-3 py-2 text-sm text-slate-100"
                      : "mr-4 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-sm text-slate-200"
                  }
                >
                  <p className="whitespace-pre-wrap leading-relaxed">
                    {msg.content}
                  </p>
                  {msg.role === "assistant" && msg.sql_query ? (
                    <details className="mt-3 border-t border-slate-800 pt-2">
                      <summary className="cursor-pointer text-[11px] font-medium text-slate-500 hover:text-slate-400">
                        SQL
                      </summary>
                      <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[11px] text-emerald-300/90">
                        {msg.sql_query}
                      </pre>
                    </details>
                  ) : null}
                </div>
              ))}
            </div>

            <div className="shrink-0 space-y-2">
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
                className="w-full resize-none rounded-xl border border-slate-700 bg-[#0b0f14] px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500/50 focus:outline-none focus:ring-1 focus:ring-indigo-500/30"
              />
              <div className="flex justify-end">
                <button
                  type="button"
                  disabled={sending}
                  onClick={() => void sendMessage()}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-500 disabled:opacity-50"
                >
                  {sending ? "Thinking…" : "Send"}
                </button>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
