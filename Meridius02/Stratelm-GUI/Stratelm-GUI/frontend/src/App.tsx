import { useState } from 'react'
import { Activity, Radio, Car, MapPin, Cpu, Trophy } from 'lucide-react'
import LiveTelemetry from './components/LiveTelemetry'
import Garage from './components/Garage'
import Tracks from './components/Tracks'
import Sandbox from './components/Sandbox'
import Strategy from './components/Strategy'

type Tab = 'live-telemetry' | 'garage' | 'tracks' | 'sandbox' | 'strategy'

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('live-telemetry')

  const navItem = (tab: Tab, icon: React.ReactNode, label: string) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
        activeTab === tab
          ? 'bg-brand-purple/20 text-brand-purple border border-brand-purple/50'
          : 'hover:bg-dark-border text-gray-400 hover:text-white'
      }`}
    >
      {icon}
      <span className="font-medium">{label}</span>
    </button>
  )

  return (
    <div className="flex h-screen bg-dark-bg text-white font-sans overflow-hidden">
      {/* Sidebar */}
      <div className="w-64 bg-dark-card border-r border-dark-border flex flex-col">
        <div className="p-6 border-b border-dark-border">
          <h1 className="text-2xl font-bold tracking-wider flex items-center gap-2">
            <Activity className="text-brand-purple" />
            STRATELM
          </h1>
          <p className="text-xs text-gray-400 mt-1 uppercase tracking-widest font-mono">Team Antasena</p>
          <p className="text-[10px] text-gray-600 mt-2 font-mono">Telemetry · Strategy · Control</p>
        </div>

        <nav className="flex-1 p-4 space-y-2">
          {navItem('live-telemetry', <Radio size={20} />, 'Live Telemetry')}
          {navItem('garage', <Car size={20} />, 'Garage')}
          {navItem('tracks', <MapPin size={20} />, 'Tracks')}
          {navItem('sandbox', <Cpu size={20} />, 'DT Sandbox')}
          {navItem('strategy', <Trophy size={20} />, 'Strategy')}
        </nav>

        <div className="p-4 border-t border-dark-border">
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            Backend Connected
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'live-telemetry' && <LiveTelemetry />}
        {activeTab === 'garage' && <Garage />}
        {activeTab === 'tracks' && <Tracks />}
        {activeTab === 'sandbox' && <Sandbox />}
        {activeTab === 'strategy' && <Strategy />}
      </div>
    </div>
  )
}

export default App
