<<<<<<< HEAD
import { useMemo, useState } from "react";
import { Send } from "lucide-react";
import ChatStudio from "../components/ChatStudio";
=======
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
>>>>>>> 714b2ea (made a sample chat layout that mimics chatgpt layou)

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
<<<<<<< HEAD
    const [planMode, setPlanMode] = useState(false);
    const [input, setInput] = useState("");
    const [messages, setMessages] = useState([
        {
            id: crypto.randomUUID(),
            role: "assistant",
            text: "Ask about trends, weaknesses, or a study plan. I’ll run the full coaching workflow.",
        },
    ]);
    const [loading, setLoading] = useState(false);
    const [pendingRunId, setPendingRunId] = useState(null);
    const [pendingQuestion, setPendingQuestion] = useState(null);
    const [clarificationDraft, setClarificationDraft] = useState({});
    const [error, setError] = useState("");

    const canSend = useMemo(
        () => !loading && !pendingRunId && input.trim().length > 0,
        [loading, pendingRunId, input],
    );

    const pushMessage = (role, text) => {
        setMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text }]);
    };

    async function postJson(path, body) {
        const response = await fetch(apiUrl(path), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        let data = null;
        try {
            data = await response.json();
        } catch {
            data = null;
        }

        if (!response.ok) {
            const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${response.status}`;
            throw new Error(detail);
        }
        return data;
    }

    async function handleSubmit(event) {
        event.preventDefault();

        if (pendingRunId && pendingQuestion) {
            setError("Please submit the clarification form below before sending a new query.");
            return;
        }

        const text = input.trim();
        if (!canSend) {
            return;
        }

        setInput("");
        setError("");
        pushMessage("user", text);
        setLoading(true);

        try {
            const queryResult = await postJson("/api/coach/query", {
                student_id: ASSUMED_STUDENT_ID,
                message: text,
                window_days: 30,
                constraints: {
                    plan_mode: planMode,
                },
            });

            if (queryResult?.status === "needs_user_input") {
                setPendingRunId(queryResult.run_id || null);
                setPendingQuestion(queryResult.question || null);
                setClarificationDraft(createClarificationDraft(queryResult.question));
                pushMessage("assistant", queryResult?.question?.prompt || "I need one more detail.");
                return;
            }

            pushMessage("assistant", normalizeFinalText(queryResult));
        } catch (submitError) {
            const message = submitError instanceof Error ? submitError.message : "Request failed";
            setError(message);
            pushMessage("assistant", "I couldn’t complete the workflow request. Please try again.");
        } finally {
            setLoading(false);
        }
    }

    async function handleClarificationSubmit(event) {
        event.preventDefault();
        if (!pendingRunId || !pendingQuestion || loading) {
            return;
        }

        setError("");
        setLoading(true);
        const answer = buildClarificationAnswerFromDraft(clarificationDraft);

        try {
            const continueResult = await postJson("/api/coach/continue", {
                run_id: pendingRunId,
                answer,
            });

            if (continueResult?.status === "needs_user_input") {
                setPendingRunId(continueResult.run_id || pendingRunId);
                setPendingQuestion(continueResult.question || null);
                setClarificationDraft(createClarificationDraft(continueResult.question));
                pushMessage("assistant", continueResult?.question?.prompt || "I need one more detail.");
                return;
            }

            setPendingRunId(null);
            setPendingQuestion(null);
            setClarificationDraft({});
            pushMessage("assistant", normalizeFinalText(continueResult));
        } catch (submitError) {
            const message = submitError instanceof Error ? submitError.message : "Clarification failed";
            setError(message);
            pushMessage("assistant", "I couldn’t apply that clarification. Please check the fields and try again.");
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="flex h-full w-full bg-white overflow-hidden -m-8"> {/* Negative margin to ignore parent padding */}

            {/* main chat */}
            <div className="flex-1 flex flex-col h-full min-w-0">

                {/* header */}
                <div className="px-8 py-6 border-b border-gray-50">
                    <div className="flex items-center gap-3 mb-2">
                        <span className="text-2xl">😴</span>
                        <h2 className="text-2xl font-bold text-gray-900">Learning Plan Strategy</h2>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                        <span className="text-xs font-bold text-gray-400 uppercase tracking-widest">Workflow Linked</span>
                        <div className="flex items-center gap-3">
                            <label className="flex items-center gap-2 text-xs font-semibold text-gray-600">
                                <input
                                    type="checkbox"
                                    checked={planMode}
                                    onChange={(event) => setPlanMode(event.target.checked)}
                                    className="accent-[#4F46E5]"
                                />
                                Study Plan Mode
                            </label>
                        </div>
                    </div>
                </div>

                {/* messages container, for ai output later */}
                <div className="flex-1 overflow-y-auto p-8 space-y-8">
                    {planMode ? (
                        <div className="max-w-3xl rounded-2xl border border-indigo-100 bg-indigo-50/40 p-4">
                            <p className="text-xs font-bold uppercase tracking-wide text-indigo-700 mb-2">Recommended Plan Request Template</p>
                            <p className="text-sm text-indigo-900 mb-2">Include as many as possible for a better plan:</p>
                            <ul className="text-sm text-gray-700 list-disc pl-5 space-y-1">
                                <li>Time horizon (e.g., “next 14 days”)</li>
                                <li>Total or daily time budget (e.g., “90 min/day”)</li>
                                <li>Topic count or priorities (e.g., “top 3 weakest topics”)</li>
                                <li>Uneven availability (e.g., weekdays 45 min, weekends 2 hours)</li>
                                <li>Milestones (quiz date, exam date)</li>
                                <li>Preferences (practice-heavy, revision-heavy, timed drills)</li>
                            </ul>
                        </div>
                    ) : null}

                    {messages.map((message) => (
                        <div key={message.id} className={`max-w-3xl ${message.role === "user" ? "ml-auto" : ""}`}>
                            <p
                                className={`leading-relaxed text-sm whitespace-pre-wrap rounded-2xl px-4 py-3 ${message.role === "user"
                                    ? "bg-indigo-50 text-indigo-900"
                                    : "bg-gray-50 text-gray-700"
                                    }`}
                            >
                                {message.text}
                            </p>
                        </div>
                    ))}
                    {loading ? (
                        <div className="max-w-3xl">
                            <p className="text-gray-500 text-sm">Running workflow...</p>
                        </div>
                    ) : null}
                    {error ? (
                        <div className="max-w-3xl">
                            <p className="text-red-600 text-xs">{error}</p>
                        </div>
                    ) : null}
                </div>

                {/* text input, to link to agent later */}
                <div className="p-8 pt-0">
                    {pendingRunId && pendingQuestion ? (
                        <form onSubmit={handleClarificationSubmit} className="max-w-3xl mx-auto mb-4 rounded-2xl border border-indigo-100 bg-indigo-50/40 p-4">
                            <p className="text-xs font-bold uppercase tracking-wide text-indigo-700 mb-3">Clarification Required</p>
                            <p className="text-sm text-indigo-900 mb-4">Fill each field or leave as <span className="font-semibold">NIL</span> if not needed.</p>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {Object.entries(clarificationDraft).map(([key, value]) => (
                                    <label key={key} className="flex flex-col gap-1 text-xs text-gray-700">
                                        <span className="font-semibold">{CLARIFICATION_FIELD_META[key]?.label || key}</span>
                                        <input
                                            type="text"
                                            value={value}
                                            onChange={(event) =>
                                                setClarificationDraft((prev) => ({
                                                    ...prev,
                                                    [key]: event.target.value,
                                                }))
                                            }
                                            placeholder={CLARIFICATION_FIELD_META[key]?.placeholder || "NIL"}
                                            className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[#4F46E5]/20"
                                        />
                                        <span className="text-[11px] text-gray-500">{CLARIFICATION_FIELD_META[key]?.hint || "Optional. Enter NIL if not needed."}</span>
                                    </label>
                                ))}
                            </div>
                            <div className="mt-4 flex justify-end">
                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="bg-[#4F46E5] text-white text-sm font-semibold px-4 py-2 rounded-lg disabled:opacity-60"
                                >
                                    Submit Clarification
                                </button>
                            </div>
                        </form>
                    ) : null}

                    <form onSubmit={handleSubmit} className="max-w-3xl mx-auto relative group">
                        <div className="absolute inset-0 bg-gradient-to-r from-[#FF517F]/20 to-[#FF7A59]/20 blur-xl opacity-0 group-focus-within:opacity-100 transition-opacity rounded-3xl" />
                        <div className="relative flex items-center bg-gray-50 border border-gray-100 rounded-[2rem] p-2 pl-6 focus-within:bg-white focus-within:ring-2 focus-within:ring-[#FF517F]/10 transition-all">
                            <input
                                type="text"
                                value={input}
                                onChange={(event) => setInput(event.target.value)}
                                disabled={Boolean(pendingRunId)}
                                placeholder={pendingRunId ? "Complete the clarification form above" : "How do I improve my Probability score?"}
                                className="flex-1 bg-transparent border-none outline-none text-sm text-gray-700 py-3"
                            />
                            <button
                                type="submit"
                                disabled={!canSend}
                                className="bg-[#4F46E5] p-3 rounded-full text-white hover:scale-105 active:scale-95 transition-all shadow-lg shadow-indigo-200 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"
                            >
                                <Send className="w-4 h-4" />
                            </button>
                        </div>
                    </form>
                </div>
            </div>
=======
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
>>>>>>> 714b2ea (made a sample chat layout that mimics chatgpt layou)

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