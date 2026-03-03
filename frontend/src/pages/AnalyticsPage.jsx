import { useEffect, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import ErrorBreakdownChart from "../components/ErrorBreakdownChart";
import MovingAverageChart from "../components/MovingAverageChart";
import TopicsNeedingAttention from "../components/TopicsNeedingAttention.jsx";
import MiniStatCard from "../components/MiniStatCard";

const DEMO_STUDENT_ID = "b980af0d-dc11-4044-b555-c2179b5a45b2";
const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

function apiUrl(path) {
    return `${API_BASE}${path}`;
}

export default function AnalyticsPage() {
    const [daysSinceLastStudy, setDaysSinceLastStudy] = useState("—");
    const [suggestedFocus, setSuggestedFocus] = useState("—");
    const [masteryLevel, setMasteryLevel] = useState("—");
    const [improvingPct, setImprovingPct] = useState("—");
    const [stagnatingPct, setStagnatingPct] = useState("—");
    const [regressingPct, setRegressingPct] = useState("—");

    useEffect(() => {
        let cancelled = false;

        async function loadSummary() {
            try {
                const query = new URLSearchParams({
                    student_id: DEMO_STUDENT_ID,
                    window_days: "180",
                });
                const response = await fetch(apiUrl(`/api/analytics/summary?${query.toString()}`));
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                if (cancelled) return;

                const days = data?.days_since_last_study;
                const focus = data?.suggested_focus_topic;
                const level = data?.mastery_level;
                const improving = data?.improving_percent;
                const stagnating = data?.stagnating_percent;
                const regressing = data?.regressing_percent;

                setDaysSinceLastStudy(Number.isInteger(days) ? `${days} Days` : "No attempts");
                setSuggestedFocus(typeof focus === "string" && focus.trim() ? focus : "N/A");
                setMasteryLevel(Number.isInteger(level) ? `Level ${level}` : "No data");
                setImprovingPct(Number.isFinite(improving) ? `${Number(improving).toFixed(0)}%` : "—");
                setStagnatingPct(Number.isFinite(stagnating) ? `${Number(stagnating).toFixed(0)}%` : "—");
                setRegressingPct(Number.isFinite(regressing) ? `${Number(regressing).toFixed(0)}%` : "—");
            } catch {
                if (!cancelled) {
                    setDaysSinceLastStudy("Unavailable");
                    setSuggestedFocus("Unavailable");
                    setMasteryLevel("Unavailable");
                    setImprovingPct("—");
                    setStagnatingPct("—");
                    setRegressingPct("—");
                }
            }
        }

        loadSummary();
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        // Main container: 3 columns total on large screens
        <div className="w-full h-full grid grid-cols-1 xl:grid-cols-3 gap-6">
            
            {/* left container, consists of top row and bottom tows */}
            <div className="xl:col-span-2 flex flex-col gap-6">
                
                {/* Left Side - Top Row */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 h-[280px]">
                    
                    {/* Pink card */}
                    <div className="bg-gradient-to-br from-[#FF517F] to-[#FF7A59] rounded-[2rem] p-6 text-white shadow-lg flex flex-col justify-between h-full">
                        <div className="flex justify-between items-start">
                            <span className="text-sm font-medium opacity-90 tracking-wide">Current Mastery Level</span>
                            <button className="hover:bg-white/20 p-1 rounded-full transition-colors cursor-pointer">
                                <MoreHorizontal className="w-5 h-5 text-white" />
                            </button>
                        </div>
                        <h2 className="text-[2.5rem] leading-none font-bold mt-2 tracking-tight">{masteryLevel}</h2>
                        <div className="flex-1 w-full flex items-center justify-center -mt-2">
                            <svg className="w-full h-16" viewBox="0 0 200 40" preserveAspectRatio="none">
                                <path d="M0 20 Q 30 5 60 20 T 130 20 T 200 15" fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="1.5" />
                                <path d="M0 25 Q 40 40 80 25 T 150 25 T 200 10" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1.5" />
                            </svg>
                        </div>
                        <div className="flex justify-between items-center text-xs opacity-90 border-t border-white/20 pt-4">
                            <div className="flex flex-col border-r border-white/20 pr-4 w-1/3">
                                <span className="mb-1 text-[10px] uppercase tracking-wider">Improving</span>
                                <span className="font-bold text-lg leading-none">{improvingPct}</span>
                            </div>
                            <div className="flex flex-col border-r border-white/20 px-4 w-1/3">
                                <span className="mb-1 text-[10px] uppercase tracking-wider">Stagnating</span>
                                <span className="font-bold text-lg leading-none">{stagnatingPct}</span>
                            </div>
                            <div className="flex flex-col pl-4 w-1/3">
                                <span className="mb-1 text-[10px] uppercase tracking-wider">Regressing</span>
                                <span className="font-bold text-lg leading-none">{regressingPct}</span>
                            </div>
                        </div>
                    </div>

                    {/* Error chart */}
                    <ErrorBreakdownChart studentId={DEMO_STUDENT_ID} windowDays={180} />
                    
                </div>

                {/* Will need to be remade into different tabs based on what we see fit later */}
                <TopicsNeedingAttention studentId={DEMO_STUDENT_ID} windowDays={180} />

            </div>

            {/* right container */}
            <div className="flex flex-col gap-6">
                
                {/* Top Small Card */}
                <MiniStatCard 
                    title="Days Since Last Study" 
                    value={daysSinceLastStudy}
                />

                {/* Middle Tall Chart */}
                <MovingAverageChart studentId={DEMO_STUDENT_ID} />

                {/* Bottom Small Card */}
                <MiniStatCard 
                    title="Suggested Focus" 
                    value={suggestedFocus}
                />

            </div>

        </div>
    );
}
