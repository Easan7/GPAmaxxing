import { MoreHorizontal } from "lucide-react";
import ErrorBreakdownChart from "../components/ErrorBreakdownChart";
import MovingAverageChart from "../components/MovingAverageChart";
import TopicsNeedingAttention from "../components/TopicsNeedingAttention.jsx";
import MiniStatCard from "../components/MiniStatCard";

const DEMO_STUDENT_ID = "b980af0d-dc11-4044-b555-c2179b5a45b2";

export default function AnalyticsPage() {
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
                        <h2 className="text-[2.5rem] leading-none font-bold mt-2 tracking-tight">Level 4</h2>
                        <div className="flex-1 w-full flex items-center justify-center -mt-2">
                            <svg className="w-full h-16" viewBox="0 0 200 40" preserveAspectRatio="none">
                                <path d="M0 20 Q 30 5 60 20 T 130 20 T 200 15" fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="1.5" />
                                <path d="M0 25 Q 40 40 80 25 T 150 25 T 200 10" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="1.5" />
                            </svg>
                        </div>
                        <div className="flex justify-between items-center text-xs opacity-90 border-t border-white/20 pt-4">
                            <div className="flex flex-col border-r border-white/20 pr-4 w-1/3">
                                <span className="mb-1 text-[10px] uppercase tracking-wider">Improving</span>
                                <span className="font-bold text-lg leading-none">%60</span>
                            </div>
                            <div className="flex flex-col border-r border-white/20 px-4 w-1/3">
                                <span className="mb-1 text-[10px] uppercase tracking-wider">Stagnant</span>
                                <span className="font-bold text-lg leading-none">%30</span>
                            </div>
                            <div className="flex flex-col pl-4 w-1/3">
                                <span className="mb-1 text-[10px] uppercase tracking-wider">Regressing</span>
                                <span className="font-bold text-lg leading-none">%10</span>
                            </div>
                        </div>
                    </div>

                    {/* Error chart */}
                    <ErrorBreakdownChart />
                    
                </div>

                {/* Will need to be remade into different tabs based on what we see fit later */}
                <TopicsNeedingAttention />

            </div>

            {/* right container */}
            <div className="flex flex-col gap-6">
                
                {/* Top Small Card */}
                <MiniStatCard 
                    title="Time Since Last Study" 
                    value="14 Days" 
                />

                {/* Middle Tall Chart */}
                <MovingAverageChart studentId={DEMO_STUDENT_ID} />

                {/* Bottom Small Card */}
                <MiniStatCard 
                    title="Suggested Focus" 
                    value="Linear Regression" 
                />

            </div>

        </div>
    );
}