import { useEffect, useState } from "react";
import { Clock, AlertCircle, BrainCircuit, Sparkles, ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const CHAT_ACTION_STORAGE_KEY = "gpa_chat_action_v1";

function apiUrl(path) {
    return `${API_BASE}${path}`;
}

function styleForAction(actionType) {
    if (actionType === "start_practice") {
        return { Icon: BrainCircuit, iconColor: "text-[#FF517F]", iconBg: "bg-[#FF517F]/10" };
    }
    if (actionType === "review_notes") {
        return { Icon: Clock, iconColor: "text-[#FF7A59]", iconBg: "bg-[#FF7A59]/10" };
    }
    if (actionType === "generate_plan") {
        return { Icon: AlertCircle, iconColor: "text-[#1A1A2E]", iconBg: "bg-gray-100" };
    }
    return { Icon: Sparkles, iconColor: "text-[#FF517F]", iconBg: "bg-[#FF517F]/10" };
}

export default function TopicsNeedingAttention({ studentId, windowDays = 180 }) {
    const navigate = useNavigate();
    const [actions, setActions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        if (!studentId) return;
        let cancelled = false;

        async function load() {
            setLoading(true);
            setError("");
            try {
                const query = new URLSearchParams({
                    student_id: studentId,
                    window_days: String(windowDays),
                });
                const response = await fetch(apiUrl(`/api/analytics/next-actions?${query.toString()}`));
                if (!response.ok) {
                    const details = await response.text();
                    throw new Error(details || `HTTP ${response.status}`);
                }
                const data = await response.json();
                if (!cancelled) {
                    setActions(Array.isArray(data?.actions) ? data.actions : []);
                }
            } catch (err) {
                if (!cancelled) {
                    const message = err instanceof Error ? err.message : "Failed to load next actions";
                    setError(message);
                    setActions([]);
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        load();
        return () => {
            cancelled = true;
        };
    }, [studentId, windowDays]);

    function buildPrefillPrompt(action) {
        const topic = action?.topic || "this topic";
        if (action?.action_type === "generate_plan") {
            return `Generate a focused study plan for ${topic} using my latest analytics.`;
        }
        if (action?.action_type === "start_practice") {
            return `Create a focused practice drill plan for ${topic} now.`;
        }
        if (action?.action_type === "review_notes") {
            return `What should I review for ${topic} based on my latest mistakes?`;
        }
        return `Help me improve ${topic} with concrete next steps.`;
    }

    function buildConstraints(action) {
        const topic = action?.topic || "General";
        if (action?.action_type === "start_practice") {
            return {
                plan_mode: true,
                time_budget_min: 25,
                focus_topics: [topic],
                topic_limit: 1,
            };
        }
        if (action?.action_type === "generate_plan") {
            return {
                plan_mode: true,
                time_budget_min: 60,
                focus_topics: [topic],
                topic_limit: 2,
            };
        }
        return {};
    }

    function handleActionClick(action) {
        const payload = {
            prefill: action?.query_prompt || buildPrefillPrompt(action),
            constraints: buildConstraints(action),
        };
        try {
            localStorage.setItem(CHAT_ACTION_STORAGE_KEY, JSON.stringify(payload));
        } catch {
            // Ignore localStorage write failures.
        }
        navigate("/chat");
    }

    return (
        <div className="bg-white rounded-[2rem] p-6 shadow-sm border border-gray-100 flex-1 flex flex-col min-h-[300px]">
            
            {/* Header */}
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h3 className="text-lg font-bold text-gray-900">Next Best Actions</h3>
                    <p className="text-sm text-gray-400 mt-1">
                        {loading ? "Building recommendations..." : error ? "Recommendations unavailable" : "Ranked from your latest analytics"}
                    </p>
                </div>
            </div>

            {/* List Container */}
            <div className="flex flex-col gap-4 flex-1">
                {!loading && actions.length === 0 && (
                    <div className="text-sm text-gray-500 p-4 rounded-xl bg-gray-50 border border-gray-100">
                        No action recommendations yet. Complete a few attempts to generate prioritized next steps.
                    </div>
                )}

                {actions.map((action) => {
                    const style = styleForAction(action.action_type);
                    const Icon = style.Icon;
                    return (
                    <div 
                        key={action.id} 
                        className="flex items-center justify-between p-4 rounded-xl border border-gray-50 hover:border-gray-200 hover:shadow-sm transition-all bg-gray-50/50 group"
                    >
                        
                        {/* Left Side: Icon & Info */}
                        <div className="flex items-center gap-4">
                            <div className={`p-3 rounded-xl ${style.iconBg}`}>
                                <Icon className={`w-6 h-6 ${style.iconColor}`} />
                            </div>
                            
                            <div className="flex flex-col">
                                <span className="font-bold text-gray-900">{action.topic}</span>
                                <div className="flex items-center gap-2 mt-1">
                                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${style.iconBg} ${style.iconColor}`}>
                                        {action.issue}
                                    </span>
                                    <span className="text-xs text-gray-500 font-medium">
                                        • {action.detail} • ~{action.eta_min} min
                                    </span>
                                </div>
                            </div>
                        </div>

                        <button
                            onClick={() => handleActionClick(action)}
                            className="flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-sm bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 hover:text-[#FF517F] hover:border-[#FF517F]/30 transition-all cursor-pointer"
                        >
                            {action.action_type === "ask_ai_tutor" && <Sparkles className="w-4 h-4 text-[#FF517F]" />}
                            {action.action_label}
                            <ArrowRight className="w-4 h-4 opacity-50 group-hover:opacity-100 group-hover:translate-x-1 transition-all" />
                        </button>

                    </div>
                )})}
            </div>
            {error && <div className="mt-4 text-xs text-red-500">{error}</div>}

        </div>
    );
}
