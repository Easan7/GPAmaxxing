import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const ASSUMED_STUDENT_ID = "b980af0d-dc11-4044-b555-c2179b5a45b2";

function apiUrl(path) {
    return `${API_BASE}${path}`;
}

async function getJson(path) {
    const response = await fetch(apiUrl(path));
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

async function patchJson(path, payload) {
    const response = await fetch(apiUrl(path), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

function formatDate(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
    });
}

function formatPlanLabel(plan, index) {
    const start = formatDate(plan.start_date);
    const end = formatDate(plan.end_date);
    const windowDays = Number(plan.window_days || 0);
    const durationText = windowDays > 0 ? `${windowDays}-day plan` : "Study plan";
    return `${index + 1}. ${durationText} • ${start} to ${end}`;
}

function formatDayHeading(dayValue) {
    if (!dayValue) return "Unscheduled";
    const parsed = new Date(dayValue);
    if (Number.isNaN(parsed.getTime())) return String(dayValue);
    return parsed.toLocaleDateString(undefined, {
        weekday: "long",
        month: "long",
        day: "numeric",
    });
}

function statusLabel(status) {
    if (status === "todo") return "To do";
    if (status === "doing") return "In progress";
    if (status === "done") return "Done";
    if (status === "skipped") return "Skipped";
    return "To do";
}

export default function MyPlanPage() {
    const [plans, setPlans] = useState([]);
    const [selectedPlanId, setSelectedPlanId] = useState("");
    const [planDetail, setPlanDetail] = useState(null);
    const [loading, setLoading] = useState(true);
    const [updatingItemId, setUpdatingItemId] = useState("");
    const [error, setError] = useState("");

    const selectedPlan = useMemo(() => plans.find((p) => p.id === selectedPlanId) || null, [plans, selectedPlanId]);

    async function loadPlans() {
        setLoading(true);
        setError("");
        try {
            const data = await getJson(`/api/plans?student_id=${ASSUMED_STUDENT_ID}`);
            const rows = Array.isArray(data?.plans) ? data.plans : [];
            setPlans(rows);
            const firstId = rows[0]?.id || "";
            setSelectedPlanId((prev) => prev || firstId);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to load plans");
        } finally {
            setLoading(false);
        }
    }

    async function loadPlanDetail(planId) {
        if (!planId) {
            setPlanDetail(null);
            return;
        }
        setError("");
        try {
            const data = await getJson(`/api/plans/${planId}`);
            setPlanDetail(data);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to load plan details");
        }
    }

    useEffect(() => {
        loadPlans();
    }, []);

    useEffect(() => {
        if (selectedPlanId) {
            loadPlanDetail(selectedPlanId);
        }
    }, [selectedPlanId]);

    async function updateStatus(itemId, status) {
        setUpdatingItemId(itemId);
        setError("");
        try {
            await patchJson(`/api/plan-items/${itemId}`, {
                student_id: ASSUMED_STUDENT_ID,
                status,
            });
            await loadPlanDetail(selectedPlanId);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to update status");
        } finally {
            setUpdatingItemId("");
        }
    }

    return (
        <div className="w-full h-full bg-[#fafafa] p-6 overflow-y-auto">
            <div className="max-w-5xl mx-auto space-y-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900">My Plan / Today</h2>
                        <p className="text-sm text-gray-500">Stay on track by updating each task as you work through your plan.</p>
                    </div>

                    <button
                        onClick={loadPlans}
                        className="px-3 py-2 rounded-lg text-sm font-semibold bg-white border border-gray-200 hover:bg-gray-50"
                    >
                        Refresh
                    </button>
                </div>

                {error ? <div className="text-sm text-red-600">{error}</div> : null}

                <div className="bg-white border border-gray-100 rounded-2xl p-4">
                    <label className="text-xs font-semibold text-gray-500">Choose a saved plan</label>
                    <select
                        value={selectedPlanId}
                        onChange={(e) => setSelectedPlanId(e.target.value)}
                        className="mt-2 w-full md:w-[420px] bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm"
                    >
                        {plans.length === 0 ? <option value="">No plans yet</option> : null}
                        {plans.map((plan, index) => (
                            <option key={plan.id} value={plan.id}>
                                {formatPlanLabel(plan, index)}
                            </option>
                        ))}
                    </select>
                    {selectedPlan ? (
                        <p className="mt-2 text-xs text-gray-500">
                            {formatDate(selectedPlan.start_date)} to {formatDate(selectedPlan.end_date)}
                        </p>
                    ) : null}
                </div>

                {loading ? <div className="text-sm text-gray-500">Loading…</div> : null}

                {!loading && !planDetail ? (
                    <div className="bg-white border border-gray-100 rounded-2xl p-6 text-sm text-gray-500">
                        No saved plan yet. Ask the AI Agent for a plan with Planning Mode enabled, then come back here to track it.
                    </div>
                ) : null}

                {planDetail?.days?.map((day) => (
                    <div key={day.day_date} className="bg-white border border-gray-100 rounded-2xl p-5">
                        <div className="text-sm font-bold text-gray-900 mb-4">{formatDayHeading(day.day_date)}</div>

                        <div className="space-y-3">
                            {(day.items || []).map((item) => {
                                const status = String(item.status || "todo");
                                const canUpdate = updatingItemId === "" || updatingItemId === item.id;

                                return (
                                    <div key={item.id} className="rounded-xl border border-gray-100 bg-gray-50/60 p-4">
                                        <div className="flex flex-wrap items-start justify-between gap-3">
                                            <div>
                                                <p className="text-sm font-semibold text-gray-900">{item.title || item.topic}</p>
                                                <p className="text-sm text-gray-600 mt-1">{item.instructions}</p>
                                                <div className="text-xs text-gray-500 mt-2">
                                                    {item.topic} • {item.minutes || 0} min • {statusLabel(status)}
                                                </div>
                                            </div>

                                            <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-lg p-1">
                                                {[
                                                    { key: "todo", label: "To do" },
                                                    { key: "doing", label: "Doing" },
                                                    { key: "done", label: "Done" },
                                                    { key: "skipped", label: "Skip" },
                                                ].map((option) => (
                                                    <button
                                                        key={option.key}
                                                        onClick={() => updateStatus(item.id, option.key)}
                                                        disabled={!canUpdate}
                                                        className={`text-xs font-semibold px-2.5 py-1.5 rounded-md transition ${status === option.key
                                                                ? "bg-indigo-600 text-white"
                                                                : "text-gray-700 hover:bg-gray-100"
                                                            } ${!canUpdate ? "opacity-50 cursor-not-allowed" : ""}`}
                                                    >
                                                        {option.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
