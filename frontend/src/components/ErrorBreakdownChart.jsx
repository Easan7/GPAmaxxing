import { MoreHorizontal } from "lucide-react";

export default function ErrorBreakdownChart() {
    // Math for the SVG Donut Chart rings
    const circumference = 2 * Math.PI * 40; // radius is 40
    
    //fake percentages
    const carelessPercent = 60;
    const conceptualPercent = 25;
    const timePercent = 15;

    // Calculate stroke lengths
    const carelessDash = `${(carelessPercent / 100) * circumference} ${circumference}`;
    const conceptualDash = `${(conceptualPercent / 100) * circumference} ${circumference}`;
    const timeDash = `${(timePercent / 100) * circumference} ${circumference}`;

    // Calculate offsets so they start exactly where the last one ended
    const carelessOffset = 0;
    const conceptualOffset = -((carelessPercent / 100) * circumference);
    const timeOffset = -(((carelessPercent + conceptualPercent) / 100) * circumference);

    return (
        <div className="bg-white rounded-[2rem] p-6 shadow-sm border border-gray-100 h-full flex flex-col justify-between">
            
            {/* Header */}
            <div className="flex justify-between items-start">
                <span className="text-sm font-bold text-gray-800 tracking-wide">Error Breakdown</span>
                <button className="hover:bg-gray-100 p-1 rounded-full transition-colors cursor-pointer text-gray-400">
                    <MoreHorizontal className="w-5 h-5" />
                </button>
            </div>

            <div className="flex items-center justify-between mt-4">
                {/* Left Side: Stats & Legend */}
                <div className="flex flex-col gap-4">
                    <div>
                        <h2 className="text-3xl font-bold text-gray-900 tracking-tight">124</h2>
                        <span className="text-xs text-gray-400 font-medium">Total Mistakes</span>
                    </div>

                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-[#FF517F]"></div>
                            <span className="text-xs text-gray-500 font-medium">Careless <span className="font-bold text-gray-800 ml-1">60%</span></span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-[#FFB020]"></div>
                            <span className="text-xs text-gray-500 font-medium">Conceptual <span className="font-bold text-gray-800 ml-1">25%</span></span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-[#1A1A2E]"></div>
                            <span className="text-xs text-gray-500 font-medium">Time Limit <span className="font-bold text-gray-800 ml-1">15%</span></span>
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
        </div>
    );
}