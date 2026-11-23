import React, { useState } from 'react';
import { Smartphone, Maximize2 } from 'lucide-react';

interface DeviceFrameProps {
  children: React.ReactNode;
}

export const DeviceFrame: React.FC<DeviceFrameProps> = ({ children }) => {
  const [framed, setFramed] = useState<boolean>(true);

  return (
    // Workspace: the header + device are ONE composition, vertically
    // centered inside a 70dvh band — 15dvh reserved above and below on any
    // viewport. The device shrinks into the band (flex-1 + max-h cap) so it
    // never clips and never forces page scroll.
    <div className="h-dvh bg-[#121517] flex flex-col items-center justify-center md:py-[15dvh] text-[#0D1C42] overflow-hidden">
      {/* Top bar controls — inside the centered composition */}
      <div className="hidden md:flex items-center justify-between w-full max-w-[420px] px-3 py-2 text-xs text-[#98A2B3] mb-2 shrink-0">
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-[#800020]" />
          <span className="font-semibold text-white tracking-wide uppercase text-[9px]">Airco PMS Staff Mobile</span>
        </div>
        <button
          onClick={() => setFramed(!framed)}
          className="flex items-center gap-1.5 px-2 py-1 rounded bg-[#0D1C42] hover:bg-[#2e3a3e] text-white/80 transition-colors text-[9px]"
        >
          {framed ? <Maximize2 className="w-3.5 h-3.5" /> : <Smartphone className="w-3.5 h-3.5" />}
          <span>{framed ? 'Expand' : 'Phone Frame'}</span>
        </button>
      </div>

      {/* Device — fills the 70dvh band up to its natural height, then shrinks
          proportionally on shorter viewports. Aspect ratio untouched. */}
      <div
        className={`w-full bg-[#FFFCFA] flex flex-col overflow-hidden transition-all duration-300 min-h-0 ${
          framed
            ? 'max-w-[420px] h-dvh md:h-auto md:flex-1 md:max-h-[844px] md:rounded-[40px] md:border-[10px] md:border-[#0D1C42] md:shadow-[0_24px_50px_rgba(0,0,0,0.6)]'
            : 'max-w-2xl h-dvh md:h-auto md:flex-1 md:rounded-2xl'
        }`}
      >
        {/* Screen Viewport */}
        <div className="flex-1 flex flex-col min-h-0 relative overflow-hidden bg-app">
          {children}
        </div>
      </div>
    </div>
  );
};
