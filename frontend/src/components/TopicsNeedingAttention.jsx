import { Clock, AlertCircle, BrainCircuit, Sparkles, ArrowRight } from "lucide-react";

export default function TopicsNeedingAttention() {
    const topics = [
        {
            id: 1,
            title: "Linear Regression Models",
            issue: "Stagnating Trend",
            detail: "Time since last study: 14 days",
            Icon: Clock,
            iconColor: "text-[#FF7A59]", // Orange
            iconBg: "bg-[#FF7A59]/10",
            action: "Generate Plan",
        },
        {
            id: 2,
            title: "Probability Distributions",
            issue: "High Careless Error Rate",
            detail: "60% of lost marks are calculation errors",
            Icon: AlertCircle,
            iconColor: "text-[#FF517F]", 
            iconBg: "bg-[#FF517F]/10",
            action: "Practice Drill",
        },
        {
            id: 3,
            title: "Hypothesis Testing",
            issue: "Conceptual Gap Detected",
            detail: "Consistently missing P-value interpretations",
            Icon: BrainCircuit,
            iconColor: "text-[#1A1A2E]", 
            iconBg: "bg-gray-100",
            action: "Ask AI Tutor",
        }
    ];

    return (
        <div className="bg-white rounded-[2rem] p-6 shadow-sm border border-gray-100 flex-1 flex flex-col min-h-[300px]">
            
            {/* Header */}
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h3 className="text-lg font-bold text-gray-900">Topics Needing Attention</h3>
                    <p className="text-sm text-gray-400 mt-1">Based on your recent quiz data and activity</p>
                </div>
                <button className="text-sm font-bold text-[#FF517F] hover:text-[#FF7A59] transition-colors">
                    View All
                </button>
            </div>

            {/* List Container */}
            <div className="flex flex-col gap-4 flex-1">
                {topics.map((topic) => (
                    <div 
                        key={topic.id} 
                        className="flex items-center justify-between p-4 rounded-xl border border-gray-50 hover:border-gray-200 hover:shadow-sm transition-all bg-gray-50/50 group"
                    >
                        
                        {/* Left Side: Icon & Info */}
                        <div className="flex items-center gap-4">
                            <div className={`p-3 rounded-xl ${topic.iconBg}`}>
                                <topic.Icon className={`w-6 h-6 ${topic.iconColor}`} />
                            </div>
                            
                            <div className="flex flex-col">
                                <span className="font-bold text-gray-900">{topic.title}</span>
                                <div className="flex items-center gap-2 mt-1">
                                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${topic.iconBg} ${topic.iconColor}`}>
                                        {topic.issue}
                                    </span>
                                    <span className="text-xs text-gray-500 font-medium">
                                        • {topic.detail}
                                    </span>
                                </div>
                            </div>
                        </div>

                        <button className="flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-sm bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 hover:text-[#FF517F] hover:border-[#FF517F]/30 transition-all cursor-pointer">
                            {topic.action === "Ask AI Tutor" && <Sparkles className="w-4 h-4 text-[#FF517F]" />}
                            {topic.action}
                            <ArrowRight className="w-4 h-4 opacity-50 group-hover:opacity-100 group-hover:translate-x-1 transition-all" />
                        </button>

                    </div>
                ))}
            </div>

        </div>
    );
}