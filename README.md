# Enterprise Order-to-Cash (O2C) Context Graph & AI Assistant

An advanced, Vercel-ready serverless platform integrating a highly interactive **Force-Directed Context Graph** with a **Generative AI Chat Assistant**. This system enables deep logistical exploration of enterprise SAP-style Order-to-Cash pipelines—empowering users to interrogate massive datasets of Sales Orders, Billing Documents, Deliveries, and Payments using natural language.

---

## 🏗 System Architecture

The overarching system architecture was designed under the strict requirement to deliver zero-latency responsiveness within a stateless, cloud-first serverless environment.

### 1. Frontend: High-Performance Canvas Graphics
- **Tech Stack**: React 18, Vite, TypeScript, TailwindCSS.
- **Rendering Engine**: D3 Force Physics and HTML5 Canvas (`react-force-graph-2d`).
- **Design Philosophy**: Rather than bogging down the DOM with thousands of native SVG nodes, the application overrides graph rendering using custom Canvas drawing pipelines (`nodeCanvasObject`). The result is a fluid, 60fps interaction experience that gracefully handles highly dense clustered logic maps (Orders natively splitting out into multiple Shipments and Billing legs), micro-animations, Dodge AI node-highlighting, and intelligent data layering.

### 2. Backend: Edge-Ready FastAPI
- **Tech Stack**: Python 3.10+, FastAPI (ASGI).
- **Design Philosophy**: The entire backend is stripped down into isolated serverless functions hosted inside `api/index.py` targeting Vercel deployment. Every HTTP endpoint boots instantly and interacts securely with absolute OS paths to generate dynamic, on-demand payloads.

---

## 💽 Database Choice: Embedded SQLite

Given the serverless deployment constraint, external cloud databases regularly suffer from cold starts and heavy network latency when interrogated dynamically through AI-synthesized SQL pipelines.

**Why SQLite?**
1. **Zero-Latency Edge Analytics**: The dataset (19 heavily interconnected SAP logistical tables) is packaged entirely as a single `o2c_context.db` file. We ship the data *alongside* the API, completely eliminating network latency.
2. **Vercel Lambda Optimization**: Serverless endpoints mount the database natively. To prevent strict Serverless Filesystem write-lock crashes, the database is mounted gracefully over the `uri=True` driver constraint appending the specific `?mode=ro` (Immutable Read-Only) instruction. This guarantees peak stability inside Vercel deployments.

---

## 🧠 LLM Prompting Strategy: The Dodge Engine

The AI logic runs on the blazing-fast Groq Llama 3.3 70B architecture, structurally divided into a precision Two-Step Pipeline (*The Dodge Engine*):

### Step 1: Text-to-SQL (Intent translation)
Instead of feeding raw unstructured data to the LLM, the backend dynamically queries the DB schema and canonical join rules, feeding them to the AI to orchestrate an exact SQL extraction query. If the user asks a conversational question, the AI bypasses the SQL execution logic to prevent unnecessary token consumption and returns a fluid Direct Answer.

### Step 2: Humanization (Data-to-Markdown)
When the SQLite DB natively executes the extracted query, the JSON output is parsed sequentially back into the Llama 70B engine. The engine acts as an Executive Analyst, processing the raw arrays and transforming them structurally into professional, enterprise-styled Markdown tables, stripping away raw programmatic artifacts, and returning localized `id` payloads to command the UI Force-Graph to highlight specific related nodes natively.

---

## 🛡️ strict Enterprise Guardrails

Because the engine permits users to execute LLM-synthesized queries against live production datasets, the system employs strict multilayer defensive constraints natively embedded deeply in both Python checks and AI prompt tuning:

- **1. Domain Restriction**: The AI persona is hard-locked to Order-to-Cash analysis. If users attempt prompt injection attacks requesting general knowledge, code generation, or unregulated analytics, the AI detects the context shift and strictly politely refuses to engage.
- **2. Query Safety Validations**: The backend engine evaluates the AST of every synthesized string. Any SQL operations containing destructive intents (`INSERT`, `UPDATE`, `DROP`, `DELETE`, `PRAGMA`) are actively flagged and rejected by the execution runner before connecting to the database.
- **3. Schema Abstraction**: Internal table architectures and variables (e.g., `business_partners`, `creation_datetime_stamp`) are heavily abstracted. The natural language layer translates technical columns implicitly into clear business english for the user output.
- **4. Graceful Error Handling**: If a targeted query runs dry, it explicitly prevents standard "Zero Results" panics, actively pivoting into a conversational fallback: *"I couldn't find any records matching that criteria."*

---

## ⚙️ Environment Variables
| Variable | Required | Description |
| -------- | -------- | ----------- |
| `GROQ_API_KEY` | Yes | Hardware-accelerated LLM API token. |

## 🚀 Deployment (Vercel)
The project is natively pre-configured for Vercel. 
- The `vercel.json` routing configuration automatically maps all `/api/*` requests to the Python serverless endpoints.
- The `o2c_context.db` physical database file is securely bundled with the deployment and executes securely against Vercel's volatile disk structure using the `?mode=ro` protection.

## 📄 License
Released under the **MIT** License.

