import { Send, Sparkles } from "lucide-react";
import ChatStudio from "../components/ChatStudio";

export default function ChatPage() {
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
                    <span className="text-xs font-bold text-gray-400 uppercase tracking-widest">5 Analysis Sources Linked</span>
                </div>

                {/* messages container, for ai output later */}
                <div className="flex-1 overflow-y-auto p-8 space-y-8">
                    <div className="max-w-3xl">
                        <p className="text-gray-600 leading-relaxed text-sm">
                            I've analyzed your recent quiz performance in <span className="font-bold text-gray-900 underline decoration-[#FF517F]/30">Linear Regression</span>. 
                            Your mastery has dipped by 15% due to a 14-day inactivity gap. However, 60% of your recent errors are flagged as "Careless," 
                            suggesting you haven't lost the concepts, just your speed and accuracy. 
                            Should we start with a 15-minute refresher on P-values?
                        </p>
                    </div>
                </div>

                {/* text input, to link to agent later */}
                <div className="p-8 pt-0">
                    <div className="max-w-3xl mx-auto relative group">
                        <div className="absolute inset-0 bg-gradient-to-r from-[#FF517F]/20 to-[#FF7A59]/20 blur-xl opacity-0 group-focus-within:opacity-100 transition-opacity rounded-3xl" />
                        <div className="relative flex items-center bg-gray-50 border border-gray-100 rounded-[2rem] p-2 pl-6 focus-within:bg-white focus-within:ring-2 focus-within:ring-[#FF517F]/10 transition-all">
                            <input 
                                type="text" 
                                placeholder="How do I improve my Probability score?" 
                                className="flex-1 bg-transparent border-none outline-none text-sm text-gray-700 py-3"
                            />
                            <button className="bg-[#4F46E5] p-3 rounded-full text-white hover:scale-105 active:scale-95 transition-all shadow-lg shadow-indigo-200">
                                <Send className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* sidebar component */}
            <ChatStudio />
        </div>
    );
}