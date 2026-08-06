import { useState, useEffect } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import Sidebar from './components/Sidebar';
import ChatView from './components/ChatView';
import SettingsModal from './components/SettingsModal';
import CanvasStudio from './components/canvas/CanvasStudio';
import CanvasLibrary from './components/canvas/CanvasLibrary';
import TipPrompt, { shouldShowTip, incrementTipCounter } from './components/TipPrompt';
import WorkspacePanel from './components/WorkspacePanel';

function ChatApp() {
  const { activeModal, activeConversationId } = useApp();
  const [showTip, setShowTip] = useState(false);

  // Tip counter — show after every ~3 conversations
  useEffect(() => {
    if (activeConversationId) {
      incrementTipCounter();
      if (shouldShowTip()) {
        setShowTip(true);
      }
    }
  }, [activeConversationId]);

  return (
    <div className="h-full flex overflow-hidden">
      <Sidebar />
      <ChatView />

      {/* Modals */}
      {activeModal === 'settings' && <SettingsModal />}
      {activeModal === 'export-import' && <SettingsModal initialTab="data" />}
      {activeModal === 'inbox' && <WorkspacePanel initialTab="inbox" />}
      {activeModal === 'artifacts' && <WorkspacePanel initialTab="artifacts" />}
      {activeModal === 'fleet' && <WorkspacePanel initialTab="fleet" />}
      {activeModal === 'canvas-studio' && <CanvasStudio />}
      {activeModal === 'canvas-library' && <CanvasLibrary />}
      {showTip && <TipPrompt onClose={() => setShowTip(false)} />}
    </div>
  );
}

// The chat app is the root and only entry view — no landing/splash gate.
export default function App() {
  return (
    <AppProvider>
      <ChatApp />
    </AppProvider>
  );
}
