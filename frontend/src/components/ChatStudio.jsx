import { Info, Plus, GraduationCap, FileText, HelpCircle, LayoutList } from "lucide-react";

export default function ChatStudio() {
    const notes = [
        { id: 1, title: "Linear Regression Mastery", content: "Declining Excitement: Factors contributing to..." },
        { id: 2, title: "Careless Error Trends", content: "Factors contributing to the perception of less impactful..." }
    ];

    return (
        <div className="w-[380px] bg-white border-l border-gray-100 flex flex-col h-full shrink-0 overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-8">
                <h3 className="font-bold text-gray-900">Studio</h3>
                <LayoutList className="w-5 h-5 text-gray-400" />
            </div>

            {/* Audio Overview Section */}
            <div className="bg-gray-50/50 rounded-2xl p-4 border border-gray-100 mb-8">
                <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold text-gray-500 uppercase tracking-wider">Study Overview</span>
                    <Info className="w-4 h-4 text-gray-400" />
                </div>
                <button className="w-full py-3 bg-white border border-gray-200 rounded-xl text-sm font-bold text-gray-700 hover:bg-gray-50 transition-all flex items-center justify-center gap-2">
                    Generate Audio Summary
                </button>
            </div>

            {/* Quick Actions Grid */}
            <div className="grid grid-cols-2 gap-3 mb-8">
                <button className="flex items-center gap-2 p-3 bg-white border border-gray-100 rounded-xl text-[11px] font-bold text-gray-600 hover:border-[#FF517F]/30 hover:text-[#FF517F] transition-all">
                    <GraduationCap className="w-4 h-4" /> Study guide
                </button>
                <button className="flex items-center gap-2 p-3 bg-white border border-gray-100 rounded-xl text-[11px] font-bold text-gray-600 hover:border-[#FF517F]/30 hover:text-[#FF517F] transition-all">
                    <FileText className="w-4 h-4" /> Briefing doc
                </button>
            </div>

            {/* Notes List */}
            <div className="flex flex-col gap-4">
                <button className="flex items-center gap-2 text-sm font-bold text-gray-400 hover:text-gray-900 transition-colors py-2 border-b border-gray-50">
                    <Plus className="w-4 h-4" /> Add note
                </button>
                {notes.map(note => (
                    <div key={note.id} className="p-4 rounded-xl border border-gray-50 bg-gray-50/30">
                        <h4 className="text-xs font-bold text-gray-800 mb-1">{note.title}</h4>
                        <p className="text-[11px] text-gray-500 line-clamp-2 leading-relaxed">{note.content}</p>
                    </div>
                ))}
            </div>
        </div>
    );
}