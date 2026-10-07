import React, { useState } from 'react';
import { Smartphone, Maximize2, Wifi, BatteryMedium, Signal } from 'lucide-react';

interface DeviceFrameProps {
  children: React.ReactNode;
}

export const DeviceFrame: React.FC<DeviceFrameProps> = ({ children }) => {
  const [framed, setFramed] = useState<boolean>(true);

  return (
    <div className="min-h-dvh bg-[#121517] flex flex-col items-center justify-start md:justify-center md:py-6 text-[#20292C]">
      {/* Top bar controls for desktop preview */}
      <div className="hidden md:flex items-center justify-between w-full max-w-[420px] px-3 py-2 text-xs text-[#8D999C] mb-2">
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-[#33B059]" />
          <span className="font-semibold text-white tracking-wide uppercase text-[10px]">AiROS Staff Mobile</span>
        </div>
        <button
          onClick={() => setFramed(!framed)}
          className="flex items-center gap-1.5 px-2 py-1 rounded bg-[#20292C] hover:bg-[#2e3a3e] text-white/80 transition-colors text-[11px]"
        >
          {framed ? <Maximize2 className="w-3.5 h-3.5" /> : <Smartphone className="w-3.5 h-3.5" />}
          <span>{framed ? 'Expand' : 'Phone Frame'}</span>
        </button>
      </div>

      {/* Main Container */}
      <div
        className={`w-full bg-[#F7F8F6] flex flex-col overflow-hidden transition-all duration-300 ${
          framed
            ? 'max-w-[420px] h-dvh md:h-[844px] md:rounded-[40px] md:border-[10px] md:border-[#20292C] md:shadow-[0_24px_50px_rgba(0,0,0,0.6)]'
            : 'max-w-2xl h-dvh md:rounded-2xl'
        }`}
      >
        {/* Mobile Device Status Bar */}
        <div className="bg-white border-b border-[#E4E8E6] px-5 pt-2 pb-1.5 flex items-center justify-between text-[12px] font-semibold text-[#20292C] select-none flex-shrink-0">
          <span>9:41</span>
          <div className="w-20 h-4 bg-black rounded-full mx-auto hidden md:block opacity-90" />
          <div className="flex items-center gap-1.5 text-[#20292C]">
            <Signal className="w-3.5 h-3.5 stroke-[2.5]" />
            <Wifi className="w-3.5 h-3.5 stroke-[2.5]" />
            <BatteryMedium className="w-4 h-4 stroke-[2.5]" />
          </div>
        </div>

        {/* Screen Viewport */}
        <div className="flex-1 flex flex-col min-h-0 relative overflow-hidden bg-[#F7F8F6]">
          {children}
        </div>
      </div>
    </div>
  );
};
