import { NavLink } from "react-router-dom";
import { LayoutDashboard, Bot, CalendarCheck } from "lucide-react";

const navItems = [
    { label: "AI Agent", icon: Bot, path: "/chat" },
    { label: "My Plan", icon: CalendarCheck, path: "/my-plan" },
    { label: "Analytics", icon: LayoutDashboard, path: "/analytics" },
];

export default function Sidebar({ collapsed }) {
    return (
        <aside
            className={`${collapsed ? "w-16" : "w-64"
                } flex flex-col bg-[#1A1A2E] text-white shrink-0 transition-all duration-300 ease-in-out h-full rounded-r-2xl shadow-xl z-20`}
        >
            <div className="flex items-center justify-center h-20 w-full mt-4">
                <div className="w-10 h-10 bg-gradient-to-tr from-pink-500 to-orange-400 rounded-xl shadow-lg shrink-0"></div>
            </div>

            <nav className="flex flex-col gap-2 mt-8 pl-4 pr-4 flex-1">
                {navItems.map((item) => (
                    <NavLink
                        key={item.label}
                        to={item.path}
                        className={({ isActive }) =>
                            `flex items-center gap-4 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 w-full ${isActive
                                ? "bg-white/10 text-white shadow-sm"
                                : "text-gray-400 hover:bg-white/5 hover:text-white"
                            }`
                        }
                        title={collapsed ? item.label : undefined}
                    >
                        <item.icon className="w-5 h-5 shrink-0" />
                        {!collapsed && <span>{item.label}</span>}
                    </NavLink>
                ))}
            </nav>
        </aside>
    );
}
