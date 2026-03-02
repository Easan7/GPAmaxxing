import { useMemo, useState } from "react";
import { Send } from "lucide-react";
import ChatStudio from "../components/ChatStudio";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
function safeGetStorageValue(key, fallback = "") {
    try {
        return localStorage.getItem(key) || fallback;
    } catch {
        return fallback;
    }
}

function safeSetStorageValue(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch {
        return;
    }
}

const DEFAULT_STUDENT_ID =
    import.meta.env.VITE_DEFAULT_STUDENT_ID ||
    safeGetStorageValue("gpa_student_id") ||
    "";

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
    const [studentId, setStudentId] = useState(DEFAULT_STUDENT_ID);
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
        () => !loading && !pendingRunId && input.trim().length > 0 && studentId.trim().length > 0,
        [loading, pendingRunId, input, studentId],
    );

    const pushMessage = (role, text) => {
        setMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text }]);
    };

    const saveStudentId = (value) => {
        const trimmed = value.trim();
        setStudentId(trimmed);
        if (trimmed) {
            safeSetStorageValue("gpa_student_id", trimmed);
        }
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
                student_id: studentId.trim(),
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
                            <input
                                type="text"
                                value={studentId}
                                onChange={(event) => saveStudentId(event.target.value)}
                                placeholder="Student ID"
                                className="w-[280px] bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-700 outline-none focus:ring-2 focus:ring-[#FF517F]/20"
                            />
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

            {/* sidebar component */}
            <ChatStudio />
        </div>
    );
}