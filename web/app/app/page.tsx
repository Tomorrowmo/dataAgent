'use client';

import { useState } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatView from '@/components/ChatView';
import DatasetsView from '@/components/DatasetsView';
import AlgorithmsView from '@/components/AlgorithmsView';
import SettingsView from '@/components/SettingsView';

type View = 'chat' | 'datasets' | 'algorithms' | 'settings';

export default function WorkspacePage() {
  const [view, setView] = useState<View>('chat');
  const [activeConv, setActiveConv] = useState<number | null>(null);
  const [convVer, setConvVer] = useState(0);

  return (
    <div className="flex h-screen">
      <Sidebar
        key={convVer}
        activeView={view}
        onChangeView={setView}
        activeConv={activeConv}
        onSelectConv={(id) => { setActiveConv(id); setView('chat'); }}
        onNewConv={() => { setActiveConv(null); setView('chat'); }}
        onConvDeleted={(id) => { if (activeConv === id) setActiveConv(null); }}
      />
      <main className="flex-1 min-w-0">
        {/* ChatView stays MOUNTED when you switch tabs (just hidden) so an
            in-flight conversation keeps streaming instead of being torn down
            and reloaded from the DB. */}
        <div className={`h-full ${view === 'chat' ? '' : 'hidden'}`}>
          <ChatView
            conversationId={activeConv}
            onConversationCreated={(id) => { setActiveConv(id); setConvVer((v) => v + 1); }}
          />
        </div>
        {view === 'datasets' && <DatasetsView />}
        {view === 'algorithms' && <AlgorithmsView />}
        {view === 'settings' && <SettingsView />}
      </main>
    </div>
  );
}
