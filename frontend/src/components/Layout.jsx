import { useState } from "react";
import { Outlet } from "react-router-dom";
import Header from "./Header";
import Sidebar from "./Sidebar";

export default function Layout() {
    const [collapsed, setCollapsed] = useState(false);

    return (
        <div className="flex h-screen bg-[#F3F2EE] text-gray-900 overflow-hidden font-sans">
            
            <Sidebar collapsed={collapsed} />

            <div className="flex flex-col flex-1 overflow-hidden">
                <Header
                    collapsed={collapsed}
                    onToggleSidebar={() => setCollapsed(!collapsed)}
                />

                <main className="flex-1 overflow-y-auto p-8">
                    <Outlet />
                </main>
            </div>
        </div>
    );
}