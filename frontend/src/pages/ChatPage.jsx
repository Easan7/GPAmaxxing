import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChatStudio from "../components/ChatStudio"; 

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const ASSUMED_STUDENT_ID = "b980af0d-dc11-4044-b555-c2179b5a45b2";

function normalizeFinalText(payload) {
    const primary = payload?.artifact?.response;
    if (typeof primary === "string" && primary.trim()) {
        return primary.trim();
    }
    const plan = payload?.plan?.response;
    if (typeof plan === "string" && plan.trim()) {
        return plan.trim();
    }
    const fallback = payload?.artifact?.summary;
    if (typeof fallback === "string" && fallback.trim()) {
        return fallback.trim();
    }
    return "I completed the workflow, but no response text was returned.";
}

function apiUrl(path) {
    return `${API_BASE}${path}`;
}

function formatAssistantContent(rawText) {
  const text = String(rawText ?? "");
  return text
    .replace(/\b(Targeted|Targetted)\s+Actions:\s*/gi, "\n**Targeted Actions:**\n")
    .replace(/\bResources\s+to\s+Review:\s*/gi, "\n**Resources to Review:**\n");
}

function normalizeNodeText(children) {
  return children
    .map((child) => {
      if (typeof child === "string") return child;
      if (child && typeof child === "object" && "props" in child && child.props?.children) {
        const nested = child.props.children;
        if (Array.isArray(nested)) return normalizeNodeText(nested);
        return typeof nested === "string" ? nested : "";
      }
      return "";
    })
    .join("")
    .trim()
    .toLowerCase();
}

async function postJson(path, payload) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Request failed with status ${response.status}`);
  }
  return response.json();
}

function normalizeOptions(options) {
  if (!Array.isArray(options) || options.length === 0) {
    return "";
  }
  return `\nOptions: ${options.join(", ")}`;
}

function formatClarificationPrompt(question) {
  const prompt = question?.prompt || "I need a bit more information before I can continue.";
  return `${prompt}${normalizeOptions(question?.options)}`;
}

function buildClarificationAnswer(question, text) {
  const trimmed = text.trim();
  const field = question?.field;

  if (field === "time_budget_min") {
    const timeBudget = Number.parseInt(trimmed, 10);
    if (!Number.isNaN(timeBudget) && timeBudget > 0) {
      return { time_budget_min: timeBudget };
    }
  }

  if (field === "mode") {
    const normalizedMode = trimmed.toLowerCase();
    if (["timed", "untimed"].includes(normalizedMode)) {
      return { mode: normalizedMode };
    }
  }

  return { message: trimmed };
}

export default function ChatPage() {
  const [messages, setMessages] = useState([
    { id: "m0", role: "assistant", content: "Hey — ask me anything about your learning progress." },
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [pendingRunId, setPendingRunId] = useState(null);
  const [pendingQuestion, setPendingQuestion] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const canSend = useMemo(() => input.trim().length > 0 && !isTyping, [input, isTyping]);

  async function handleSend() {
    if (!canSend) return;

    const text = input.trim();
    setInput("");

    const userMsg = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);

    setIsTyping(true);

    try {
      const isContinuation = Boolean(pendingRunId);
      const endpoint = isContinuation ? "/api/coach/continue" : "/api/coach/query";
      const payload = isContinuation
        ? {
            run_id: pendingRunId,
            answer: buildClarificationAnswer(pendingQuestion, text),
          }
        : {
            student_id: ASSUMED_STUDENT_ID,
            message: text,
            window_days: 180,
            constraints: {},
          };

      const data = await postJson(endpoint, payload);

      if (data?.status === "needs_user_input") {
        setPendingRunId(data.run_id);
        setPendingQuestion(data.question ?? null);
        const botMsg = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: formatClarificationPrompt(data.question),
        };
        setMessages((prev) => [...prev, botMsg]);
        return;
      }

      setPendingRunId(null);
      setPendingQuestion(null);
      const botMsg = { id: crypto.randomUUID(), role: "assistant", content: normalizeFinalText(data) };
      setMessages((prev) => [...prev, botMsg]);
    } catch (error) {
      const details = error instanceof Error ? error.message : "Unknown error";
      const botMsg = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `I couldn't reach the backend right now. ${details}`,
      };
      setMessages((prev) => [...prev, botMsg]);
    } finally {
      setIsTyping(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="h-full w-full flex">
      {/* Main chat column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="h-14 px-6 flex items-center border-b border-gray-100 bg-white shrink-0">
          <div className="text-sm font-semibold text-gray-900">AI Agent</div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto bg-[#fafafa]">
          <div className="max-w-3xl mx-auto px-4 py-6 pb-28 space-y-6">
            {messages.map((m) => (
              <MessageRow key={m.id} role={m.role} content={m.content} />
            ))}

            {isTyping && (
              <div className="flex gap-3">
                <Avatar role="assistant" />
                <div className="rounded-2xl bg-white border border-gray-100 px-4 py-3 shadow-sm">
                  <TypingDots />
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-gray-100 bg-white shrink-0">
          <div className="max-w-3xl mx-auto px-4 py-4">
            <div className="rounded-2xl border border-gray-200 bg-white shadow-sm flex items-end gap-2 p-3">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder="Message AI Agent..."
                className="flex-1 resize-none outline-none text-sm leading-6 max-h-40 py-2"
              />
              <button
                onClick={handleSend}
                disabled={!canSend}
                className={`h-9 px-4 rounded-xl text-sm font-semibold transition
                  ${
                    canSend
                      ? "bg-indigo-600 text-white hover:bg-indigo-700"
                      : "bg-gray-100 text-gray-400 cursor-not-allowed"
                  }`}
              >
                Send
              </button>
            </div>
            <div className="text-[12px] text-gray-400 mt-2 px-1">
              Enter to send • Shift+Enter for new line
            </div>
          </div>
        </div>
      </div>

      {/* ✅ Keep your Studio sidebar */}
      <ChatStudio />
    </div>
  );
}

function MessageRow({ role, content }) {
  const isUser = role === "user";
  const displayContent = isUser ? content : formatAssistantContent(content);

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <Avatar role="assistant" />}

      <div
        className={
          isUser
            ? "max-w-[85%] rounded-2xl bg-indigo-600 text-white px-4 py-3 shadow-sm"
            : "max-w-[85%] rounded-2xl bg-white border border-gray-100 px-4 py-3 shadow-sm"
        }
      >
        {role === "assistant" ? (
          <div className="prose prose-sm max-w-none prose-headings:mt-4 prose-headings:mb-2 prose-p:my-2 prose-li:my-1">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                strong: ({ children }) => {
                  const text = normalizeNodeText(Array.isArray(children) ? children : [children]);
                  const shouldUnderline =
                    text.includes("targeted actions:") || text.includes("resources to review:");
                  return (
                    <strong className={shouldUnderline ? "underline underline-offset-4" : undefined}>
                      {children}
                    </strong>
                  );
                },
              }}
            >
              {displayContent}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="text-sm leading-6 whitespace-pre-wrap">{displayContent}</div>
        )}
      </div>

      {isUser && <Avatar role="user" />}
    </div>
  );
}

function Avatar({ role }) {
  const isUser = role === "user";
  return (
    <div
      className={`w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0
      ${isUser ? "bg-gray-900 text-white" : "bg-gradient-to-br from-pink-500 to-orange-400 text-white"}`}
      title={isUser ? "You" : "Coach"}
    >
      {isUser ? "You" : "AI"}
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full bg-gray-300 animate-bounce [animation-delay:-0.2s]" />
      <span className="w-2 h-2 rounded-full bg-gray-300 animate-bounce [animation-delay:-0.1s]" />
      <span className="w-2 h-2 rounded-full bg-gray-300 animate-bounce" />
    </div>
  );
}
