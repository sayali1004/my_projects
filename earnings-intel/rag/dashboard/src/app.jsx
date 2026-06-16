import { useState, useEffect } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

const API = "http://localhost:8000";

// ── Colours ──────────────────────────────────────────────────────────────────
const BULLISH  = "#1D9E75";
const BEARISH  = "#E24B4A";
const NEUTRAL  = "#888780";
const ANOMALY  = "#F59E0B";
const PURPLE   = "#534AB7";

const scoreColor = (score) =>
  score >= 60 ? BULLISH : score <= 40 ? BEARISH : NEUTRAL;

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmt = (n, d = 1) => (n == null ? "—" : Number(n).toFixed(d));

// ── Components ────────────────────────────────────────────────────────────────

function ScoreBadge({ label }) {
  const color =
    label === "bullish" ? BULLISH : label === "bearish" ? BEARISH : NEUTRAL;
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: "2px 8px",
      borderRadius: 99, background: color + "22", color,
    }}>
      {label}
    </span>
  );
}

function StatCard({ title, value, sub, color }) {
  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: 10,
      padding: "14px 16px", flex: 1,
    }}>
      <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: color || "inherit" }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ── Leaderboard tab ───────────────────────────────────────────────────────────

function Leaderboard({ onSelect }) {
  const [data, setData] = useState([]);

  useEffect(() => {
    fetch(`${API}/leaderboard`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData([]));
  }, []);

  return (
    <div>
      <div style={{ fontSize: 13, color: "#888", marginBottom: 12 }}>
        Average Earnings Surprise Score by company — higher = more positive tone shift
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["#", "Ticker", "Avg Score", "Avg 1D Return", "Filings", "Bullish", "Bearish", "Anomalies"].map(h => (
                <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontSize: 11, color: "#888", fontWeight: 500 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr
                key={row.ticker}
                onClick={() => onSelect(row.ticker)}
                style={{ borderBottom: "1px solid var(--border)", cursor: "pointer" }}
                onMouseEnter={e => e.currentTarget.style.background = "#f5f5f5"}
                onMouseLeave={e => e.currentTarget.style.background = ""}
              >
                <td style={{ padding: "8px 10px", color: "#888" }}>{i + 1}</td>
                <td style={{ padding: "8px 10px", fontWeight: 600 }}>{row.ticker}</td>
                <td style={{ padding: "8px 10px" }}>
                  <span style={{ color: scoreColor(row.avg_score), fontWeight: 600 }}>
                    {fmt(row.avg_score)}
                  </span>
                </td>
                <td style={{ padding: "8px 10px", color: row.avg_return_1d >= 0 ? BULLISH : BEARISH }}>
                  {row.avg_return_1d >= 0 ? "+" : ""}{fmt(row.avg_return_1d, 3)}%
                </td>
                <td style={{ padding: "8px 10px" }}>{row.filings}</td>
                <td style={{ padding: "8px 10px", color: BULLISH }}>{row.bullish_count}</td>
                <td style={{ padding: "8px 10px", color: BEARISH }}>{row.bearish_count}</td>
                <td style={{ padding: "8px 10px", color: ANOMALY }}>{row.anomaly_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Company detail tab ────────────────────────────────────────────────────────

function CompanyDetail({ ticker, onBack }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!ticker) return;
    fetch(`${API}/ticker/${ticker}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, [ticker]);

  if (!data) return <div style={{ padding: 20, color: "#888" }}>Loading {ticker}...</div>;

  const chartData = [...data.history]
    .filter(r => r.filing_type !== "8-K")
    .reverse()
    .map(r => ({
      date: r.filed_date?.slice(0, 7),
      score: r.surprise_score,
      return: r.return_1d_pct,
      hedging: r.hedging_ratio,
    }));

  return (
    <div>
      <button onClick={onBack} style={{
        background: "none", border: "1px solid var(--border)",
        borderRadius: 6, padding: "4px 12px", cursor: "pointer",
        fontSize: 13, marginBottom: 16,
      }}>← Back</button>

      <div style={{ display: "flex", gap: 10, marginBottom: 20 }}>
        <StatCard title="Ticker" value={data.ticker} />
        <StatCard title="Avg Score" value={fmt(data.avg_score)} color={scoreColor(data.avg_score)} />
        <StatCard title="Total Filings" value={data.total_filings} />
      </div>

      <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 8 }}>Surprise Score over time</div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
          <Tooltip />
          <Line type="monotone" dataKey="score" stroke={PURPLE} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>

      <div style={{ fontSize: 13, fontWeight: 500, margin: "16px 0 8px" }}>Hedging ratio over time</div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
          <Tooltip />
          <Line type="monotone" dataKey="hedging" stroke={ANOMALY} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>

      <div style={{ fontSize: 13, fontWeight: 500, margin: "16px 0 8px" }}>Filing history</div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            {["Date", "Type", "Score", "Label", "1D Return", "Hedging", "Anomaly"].map(h => (
              <th key={h} style={{ padding: "4px 8px", textAlign: "left", fontSize: 11, color: "#888" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.history.map((r, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "6px 8px" }}>{r.filed_date?.slice(0, 10)}</td>
              <td style={{ padding: "6px 8px" }}>{r.filing_type}</td>
              <td style={{ padding: "6px 8px", color: scoreColor(r.surprise_score), fontWeight: 600 }}>{fmt(r.surprise_score)}</td>
              <td style={{ padding: "6px 8px" }}><ScoreBadge label={r.surprise_label} /></td>
              <td style={{ padding: "6px 8px", color: r.return_1d_pct >= 0 ? BULLISH : BEARISH }}>
                {r.return_1d_pct != null ? `${r.return_1d_pct >= 0 ? "+" : ""}${fmt(r.return_1d_pct, 2)}%` : "—"}
              </td>
              <td style={{ padding: "6px 8px" }}>{fmt(r.hedging_ratio, 3)}</td>
              <td style={{ padding: "6px 8px" }}>{r.is_anomaly ? "⚠️" : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── RAG Chat tab ──────────────────────────────────────────────────────────────

function RAGChat() {
  const [question, setQuestion] = useState("");
  const [ticker, setTicker] = useState("");
  const [messages, setMessages] = useState([{
    role: "assistant",
    content: "Ask me anything about SEC filings. Try: 'What did Apple say about iPhone margins last quarter?' or 'Which companies mentioned supply chain risks?'",
  }]);
  const [loading, setLoading] = useState(false);

  const ask = async () => {
    if (!question.trim()) return;
    const q = question.trim();
    setMessages(m => [...m, { role: "user", content: q }]);
    setQuestion("");
    setLoading(true);

    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, ticker: ticker || null, n_results: 5 }),
      });
      const data = await res.json();
      setMessages(m => [...m, {
        role: "assistant",
        content: data.answer,
        sources: data.sources,
      }]);
    } catch (e) {
      setMessages(m => [...m, {
        role: "assistant",
        content: "Error connecting to RAG server. Make sure FastAPI and Ollama are running.",
      }]);
    }
    setLoading(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 180px)" }}>
      <div style={{ flex: 1, overflowY: "auto", marginBottom: 12 }}>
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 16 }}>
            <div style={{
              fontSize: 11, fontWeight: 600, color: "#888", marginBottom: 4,
              textTransform: "uppercase", letterSpacing: ".05em",
            }}>
              {m.role === "user" ? "You" : "EarningsEdge AI"}
            </div>
            <div style={{
              background: m.role === "user" ? "#f5f5f5" : "white",
              border: "1px solid var(--border)", borderRadius: 8,
              padding: "10px 14px", fontSize: 13, lineHeight: 1.65,
            }}>
              {m.content}
            </div>
            {m.sources && (
              <div style={{ marginTop: 6 }}>
                <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>Sources:</div>
                {m.sources.map((s, j) => (
                  <div key={j} style={{
                    fontSize: 11, color: "#555", background: "#f9f9f9",
                    border: "1px solid var(--border)", borderRadius: 6,
                    padding: "4px 10px", marginBottom: 3,
                  }}>
                    {s.ticker} · {s.filing_type} · {s.filed_date?.slice(0, 10)}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ fontSize: 13, color: "#888" }}>Thinking...</div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={ticker}
          onChange={e => setTicker(e.target.value)}
          placeholder="Ticker (optional)"
          style={{
            width: 120, padding: "8px 12px", borderRadius: 8,
            border: "1px solid var(--border)", fontSize: 13,
          }}
        />
        <input
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => e.key === "Enter" && ask()}
          placeholder="Ask about any earnings filing..."
          style={{
            flex: 1, padding: "8px 12px", borderRadius: 8,
            border: "1px solid var(--border)", fontSize: 13,
          }}
        />
        <button onClick={ask} disabled={loading} style={{
          padding: "8px 20px", borderRadius: 8, border: "none",
          background: PURPLE, color: "white", fontWeight: 600,
          fontSize: 13, cursor: "pointer",
        }}>
          Ask
        </button>
      </div>
    </div>
  );
}

// ── Anomalies tab ─────────────────────────────────────────────────────────────

function Anomalies() {
  const [data, setData] = useState([]);

  useEffect(() => {
    fetch(`${API}/anomalies`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData([]));
  }, []);

  return (
    <div>
      <div style={{ fontSize: 13, color: "#888", marginBottom: 12 }}>
        {data.length} filings flagged as anomalous by Isolation Forest — statistically unusual combinations of NLP signals
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            {["Ticker", "Type", "Date", "Score", "Sentiment Δ", "Hedging", "1D Return"].map(h => (
              <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontSize: 11, color: "#888", fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "8px 10px", fontWeight: 600 }}>{r.ticker}</td>
              <td style={{ padding: "8px 10px" }}>{r.filing_type}</td>
              <td style={{ padding: "8px 10px" }}>{r.filed_date?.slice(0, 10)}</td>
              <td style={{ padding: "8px 10px", color: scoreColor(r.surprise_score), fontWeight: 600 }}>{fmt(r.surprise_score)}</td>
              <td style={{ padding: "8px 10px", color: r.sentiment_delta >= 0 ? BULLISH : BEARISH }}>
                {r.sentiment_delta >= 0 ? "+" : ""}{fmt(r.sentiment_delta, 3)}
              </td>
              <td style={{ padding: "8px 10px" }}>{fmt(r.hedging_ratio, 3)}</td>
              <td style={{ padding: "8px 10px", color: r.return_1d_pct >= 0 ? BULLISH : BEARISH }}>
                {r.return_1d_pct != null ? `${r.return_1d_pct >= 0 ? "+" : ""}${fmt(r.return_1d_pct, 2)}%` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState("leaderboard");
  const [selectedTicker, setSelectedTicker] = useState(null);

  const tabs = [
    { id: "leaderboard", label: "Leaderboard" },
    { id: "anomalies",   label: "Anomalies" },
    { id: "chat",        label: "AI Chat" },
  ];

  return (
    <div style={{
      maxWidth: 1100, margin: "0 auto", padding: "24px 20px",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      "--border": "#e5e5e5",
    }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 22, fontWeight: 700 }}>EarningsEdge</div>
          <div style={{
            fontSize: 11, fontWeight: 600, padding: "2px 8px",
            borderRadius: 99, background: PURPLE + "22", color: PURPLE,
          }}>Financial Intelligence</div>
        </div>
        <div style={{ fontSize: 13, color: "#888" }}>
          NLP-powered earnings analysis across 30 S&P 500 companies · 1,258 filings scored
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: "1px solid var(--border)", paddingBottom: 0 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => { setTab(t.id); setSelectedTicker(null); }} style={{
            padding: "6px 16px", border: "none", background: "none",
            fontSize: 13, fontWeight: 500, cursor: "pointer",
            borderBottom: tab === t.id ? `2px solid ${PURPLE}` : "2px solid transparent",
            color: tab === t.id ? PURPLE : "#666",
            marginBottom: -1,
          }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "leaderboard" && !selectedTicker && (
        <Leaderboard onSelect={ticker => { setSelectedTicker(ticker); }} />
      )}
      {tab === "leaderboard" && selectedTicker && (
        <CompanyDetail ticker={selectedTicker} onBack={() => setSelectedTicker(null)} />
      )}
      {tab === "anomalies" && <Anomalies />}
      {tab === "chat" && <RAGChat />}
    </div>
  );
}