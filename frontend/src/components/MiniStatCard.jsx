export default function MiniStatCard({ title, value }) {
    return (
        <div className="bg-[#FFE5E5] rounded-[2rem] p-6 flex flex-col items-center justify-center h-[100px] shadow-sm border border-[#FF517F]/10 text-center transition-transform hover:scale-[1.02]">
            <span className="text-[10px] font-bold text-[#FF517F] uppercase tracking-wider opacity-80 mb-1">
                {title}
            </span>
            <span className="text-xl font-extrabold text-[#FF517F] tracking-tight">
                {value}
            </span>
        </div>
    );
}