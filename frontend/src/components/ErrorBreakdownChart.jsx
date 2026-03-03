import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

function apiUrl(path) {
    return `${API_BASE}${path}`;
}

export default function ErrorBreakdownChart({ studentId, windowDays = 180 }) {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [breakdown, setBreakdown] = useState({
        total_mistakes: 0,
        careless: { count: 0, percent: 0 },
        conceptual: { count: 0, percent: 0 },
        time_pressure: { count: 0, percent: 0 },
    });

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
                const response = await fetch(apiUrl(`/api/analytics/error-breakdown?${query.toString()}`));
                if (!response.ok) {
                    const details = await response.text();
                    throw new Error(details || `HTTP ${response.status}`);
                }
                const data = await response.json();
                if (!cancelled) {
                    setBreakdown({
                        total_mistakes: data.total_mistakes ?? 0,
                        careless: data.careless ?? { count: 0, percent: 0 },
                        conceptual: data.conceptual ?? { count: 0, percent: 0 },
                        time_pressure: data.time_pressure ?? { count: 0, percent: 0 },
                    });
                }
            } catch (err) {
                if (!cancelled) {
                    const message = err instanceof Error ? err.message : "Failed to load error breakdown";
                    setError(message);
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

    const { carelessPercent, conceptualPercent, timePercent, carelessCount, conceptualCount, timeCount, totalMistakes } =
        useMemo(() => {
            const careless = Number(breakdown.careless?.percent ?? 0);
            const conceptual = Number(breakdown.conceptual?.percent ?? 0);
            const timePressure = Number(breakdown.time_pressure?.percent ?? 0);
            return {
                carelessPercent: careless,
                conceptualPercent: conceptual,
                timePercent: timePressure,
                carelessCount: Number(breakdown.careless?.count ?? 0),
                conceptualCount: Number(breakdown.conceptual?.count ?? 0),
                timeCount: Number(breakdown.time_pressure?.count ?? 0),
                totalMistakes: Number(breakdown.total_mistakes ?? 0),
            };
        }, [breakdown]);

    const circumference = 2 * Math.PI * 40;
    const carelessDash = `${(carelessPercent / 100) * circumference} ${circumference}`;
    const conceptualDash = `${(conceptualPercent / 100) * circumference} ${circumference}`;
    const timeDash = `${(timePercent / 100) * circumference} ${circumference}`;

    const carelessOffset = 0;
    const conceptualOffset = -((carelessPercent / 100) * circumference);
    const timeOffset = -(((carelessPercent + conceptualPercent) / 100) * circumference);

    return (
        <div className="bg-white rounded-[2rem] p-6 shadow-sm border border-gray-100 h-full flex flex-col justify-between">
            
            {/* Header */}
            <div className="flex items-start">
                <span className="text-sm font-bold text-gray-800 tracking-wide">Error Breakdown</span>
            </div>
            <div className="mt-2 text-xs font-semibold text-gray-400">
                {loading ? "Loading..." : error ? "Unavailable" : `Last ${windowDays} days`}
            </div>

            <div className="flex items-center justify-between mt-4">
                {/* Left Side: Stats & Legend */}
                <div className="flex flex-col gap-4">
                    <div>
                        <h2 className="text-3xl font-bold text-gray-900 tracking-tight">{totalMistakes}</h2>
                        <span className="text-xs text-gray-400 font-medium">Total Mistakes</span>
                    </div>

                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-[#FF517F]"></div>
                            <span className="text-xs text-gray-500 font-medium">
                                Careless <span className="font-bold text-gray-800 ml-1">{carelessPercent.toFixed(1)}%</span>
                                <span className="ml-1 text-gray-400">({carelessCount})</span>
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-[#FFB020]"></div>
                            <span className="text-xs text-gray-500 font-medium">
                                Conceptual <span className="font-bold text-gray-800 ml-1">{conceptualPercent.toFixed(1)}%</span>
                                <span className="ml-1 text-gray-400">({conceptualCount})</span>
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-[#1A1A2E]"></div>
                            <span className="text-xs text-gray-500 font-medium">
                                Time Limit <span className="font-bold text-gray-800 ml-1">{timePercent.toFixed(1)}%</span>
                                <span className="ml-1 text-gray-400">({timeCount})</span>
                            </span>
                        </div>
                    </div>
                </div>

                {/* Right Side: Donut Chart SVG */}
                <div className="relative w-32 h-32 flex items-center justify-center">
                    
                    {/* Decorative center cross from your mockup */}
                    <div className="absolute flex items-center justify-center">
                        <div className="w-8 h-2 bg-[#FF7A59] rounded-full rotate-45 absolute opacity-80"></div>
                        <div className="w-8 h-2 bg-[#FF7A59] rounded-full -rotate-45 absolute opacity-80"></div>
                    </div>

                    {/* SVG Rings */}
                    <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                        {/* Background Track */}
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="#F3F2EE" strokeWidth="10" />
                        
                        {/* Time Limit Segment (Dark Blue) */}
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="#1A1A2E" strokeWidth="10" 
                            strokeDasharray={timeDash} strokeDashoffset={timeOffset} strokeLinecap="round" />
                        
                        {/* Conceptual Segment (Yellow/Orange) */}
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="#FFB020" strokeWidth="10" 
                            strokeDasharray={conceptualDash} strokeDashoffset={conceptualOffset} strokeLinecap="round" />
                        
                        {/* Careless Segment (Pink) */}
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="#FF517F" strokeWidth="10" 
                            strokeDasharray={carelessDash} strokeDashoffset={carelessOffset} strokeLinecap="round" />
                    </svg>
                </div>
            </div>
            {error && <div className="mt-3 text-xs text-red-500">{error}</div>}
        </div>
    );
}
