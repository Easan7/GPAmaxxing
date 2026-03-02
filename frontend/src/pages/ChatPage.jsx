import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChatStudio from "../components/ChatStudio"; // <-- adjust path if needed

const MOCK_STUDY_PLAN = `Based on the provided analytics, the study plan focuses on areas where your mastery is lower and where there are signs of conceptual misunderstanding. Given the metrics you've provided, here's how we can refine your plan:

### Revised Study Plan

Title: Focused Session Plan

1. User-Centred Design (13 minutes)
   - Current mastery: 46.72% with high uncertainty (58.52%). Focus here is essential as mastery is below the 50% threshold.
   - Practice questions similar to: "What are the key principles of User-Centred Design?" This can help increase both your knowledge and confidence, which currently stands at a risk of decay due to your low trend.

2. Interaction Design (8 minutes)
   - Current mastery: 52.08%, but with a conceptual understanding issue noted (1.0 indicating you're facing challenges in this area).
   - Focus on questions like: "How does interaction design influence user experience?" Dedicate time to clarify conceptual misunderstandings.

3. Prototyping (8 minutes)
   - Mastery is currently unknown due to noted conceptual errors.
   - Practice analyzing prototyping scenarios with questions such as: "What are the advantages of low-fidelity prototyping?" This will help address your conceptual gaps.

4. Ideation (8 minutes)
   - While you performed well in your attempts (correct with 80% confidence), your mastery is at 51.83%, suggesting continuous practice will reinforce this area.
   - Example of a question to work on: "What techniques can be used to enhance creative thinking during ideation sessions?" This will maintain your confidence while building further understanding.

5. Qualitative Analysis (8 minutes)
   - Although your mastery in this area is higher than others, regular practice will help mitigate uncertainty (12.83%).
   - Engage with questions like: "What methods can be used to analyze qualitative data effectively?"

### Key Example
- For Ideation, you have answered previously with confidence. For instance, the question, “Why should teams defer judgment during brainstorming?”, which you answered correctly in 90 seconds with 80% confidence, demonstrates that you’re building a solid foundation. Continue to work on enhancing confidence through repeated practice and deeper exploration of concepts related to brainstorming tactics.

### Summary
This study plan is specifically designed to target your uncertainties and areas where conceptual understanding is weak. By focusing on both practice and theory, you can enhance your overall mastery while ensuring you have a confident grasp on the critical concepts in your field. Adjust timing based on your comfort level, but aim to revisit these topics repetitively to solidify your learning.`;

function mockCoachReply(userText) {
  const t = userText.toLowerCase();
  if (t.includes("study plan") || t.includes("make a plan")) return MOCK_STUDY_PLAN;
  return `Got it. Ask me for a **study plan** and I’ll generate one based on your analytics.`;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const ASSUMED_STUDENT_ID = "b980af0d-dc11-4044-b555-c2179b5a45b2";

const CLARIFICATION_FIELD_ORDER = [
    "time_budget_min",
    "time_horizon_days",
    "daily_budget_min",
    "topic_limit",
    "focus_topics",
    "generic_plan",
];

function createClarificationDraft(question) {
    const expected = question?.expected || {};
    const draft = {};
    for (const key of CLARIFICATION_FIELD_ORDER) {
        if (expected[key]) {
            draft[key] = "NIL";
        }
    }
    if (Object.keys(draft).length === 0) {
        draft.message = "NIL";
    }
    return draft;
}

function isNil(value) {
    return String(value ?? "").trim().toUpperCase() === "NIL" || String(value ?? "").trim() === "";
}

function buildClarificationAnswerFromDraft(draft) {
    const answer = {};

    for (const [key, rawValue] of Object.entries(draft || {})) {
        if (isNil(rawValue)) {
            continue;
        }

        const value = String(rawValue).trim();
        if (key === "focus_topics") {
            const topics = value
                .split(/,| and |;|\+|\//i)
                .map((item) => item.trim())
                .filter(Boolean);
            if (topics.length > 0) {
                answer.focus_topics = topics;
            }
            continue;
        }

        if (key === "generic_plan") {
            answer.generic_plan = /^(true|yes|y|1)$/i.test(value);
            continue;
        }

        if (["time_budget_min", "time_horizon_days", "daily_budget_min", "topic_limit"].includes(key)) {
            const numeric = Number.parseInt(value, 10);
            if (!Number.isNaN(numeric) && numeric > 0) {
                answer[key] = numeric;
            }
            continue;
        }

        answer[key] = value;
    }

    if (Object.keys(answer).length === 0) {
        answer.generic_plan = true;
    }
    return answer;
}

const CLARIFICATION_FIELD_META = {
    time_budget_min: {
        label: "Total Time (minutes)",
        hint: "Enter total study time in minutes, or NIL.",
        placeholder: "e.g. 180 or NIL",
    },
    time_horizon_days: {
        label: "Plan Horizon (days)",
        hint: "How many days this plan should cover, or NIL.",
        placeholder: "e.g. 14 or NIL",
    },
    daily_budget_min: {
        label: "Daily Time (minutes)",
        hint: "Optional daily budget, or NIL.",
        placeholder: "e.g. 60 or NIL",
    },
    topic_limit: {
        label: "Number of Topics",
        hint: "How many topics to include, or NIL.",
        placeholder: "e.g. 2 or NIL",
    },
    focus_note: {
        label: "Focus Preference (optional)",
        hint: "Free text guidance (not strict topic matching), or NIL.",
        placeholder: "e.g. prioritize practical application or NIL",
    },
    generic_plan: {
        label: "Use Generic Plan",
        hint: "true / false or NIL.",
        placeholder: "e.g. true or NIL",
    },
};

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

export default function ChatPage() {
  const [messages, setMessages] = useState([
    { id: "m0", role: "assistant", content: "Hey — ask me anything about your learning progress." },
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const canSend = useMemo(() => input.trim().length > 0 && !isTyping, [input, isTyping]);

  function handleSend() {
    if (!canSend) return;

    const text = input.trim();
    setInput("");

    const userMsg = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);

    setIsTyping(true);

    // Mock delay (feels real). Replace with fetch() later.
    window.setTimeout(() => {
      const reply = mockCoachReply(text);
      const botMsg = { id: crypto.randomUUID(), role: "assistant", content: reply };
      setMessages((prev) => [...prev, botMsg]);
      setIsTyping(false);
    }, 700);
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
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : (
          <div className="text-sm leading-6 whitespace-pre-wrap">{content}</div>
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