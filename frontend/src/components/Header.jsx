import { PanelLeft, PanelRight } from "lucide-react";

export default function Header({ collapsed, onToggleSidebar }) {
    return (
        <header className="flex items-center gap-4 px-8 h-20 bg-[#F3F2EE] shrink-0 w-full">
            <button
                onClick={onToggleSidebar}
                className="p-2 rounded-lg text-gray-500 hover:text-gray-900 hover:bg-gray-200 transition-colors cursor-pointer"
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
                {!collapsed ? (
                    <PanelLeft className="w-6 h-6" />
                ) : (
                    <PanelRight className="w-6 h-6" />
                )}
            </button>
            
            <h1 className="text-gray-900 font-bold text-2xl tracking-wide">
                Analytics
            </h1>
            
            <div className="ml-auto"></div>
        </header>
    );
}