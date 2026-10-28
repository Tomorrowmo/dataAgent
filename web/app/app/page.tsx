'use client';

import { useState } from 'react';
import Sidebar from '@/components/Sidebar';
import ChatView from '@/components/ChatView';
import DatasetsView from '@/components/DatasetsView';
import AlgorithmsView, { TemplatesView } from '@/components/AlgorithmsView';
import SettingsView from '@/components/SettingsView';
import AboutView from '@/components/AboutView';
import WindTunnelView from '@/components/WindTunnelView';
import SkillsView from '@/components/SkillsView';
import FeedbackButton from '@/components/FeedbackButton';
import FeedbackInbox from '@/components/FeedbackInbox';

type View = 'chat' | 'datasets' | 'algorithms' | 'templates' | 'skills' | 'windtunnel' | 'feedback' | 'settings' | 'about';

export default function WorkspacePage() {
  const [view, setView] = useState<View>('chat');
  const [activeConv, setActiveConv] = useState<number | null>(null);
  const [convVer, setConvVer] = useState(0);
  // A suggestion clicked in the datasets view that should be asked in chat:
  // jump to the chat tab and let ChatView pick it up (nonce makes repeat clicks
  // of the same prompt re-fire).
  const [pendingAsk, setPendingAsk] = useState<{ prompt: string; datasetId: number; nonce: number } | null>(null);
  // "查看完整表格" from chat's data preview → open the datasets tab on that dataset.
  const [focusDataset, setFocusDataset] = useState<{ id: number; nonce: number } | null>(null);
  // The dataset currently open in the datasets view — recorded as context when a
  // feedback note is dropped there.
  const [activeDataset, setActiveDataset] = useState<number | null>(null);
  // Bumped whenever the datasets view adds or deletes datasets. ChatView stays
  // mounted while hidden, so it needs an explicit nudge to re-read the list —
  // otherwise its top-right picker still offers datasets that were just deleted.
  const [dsVer, setDsVer] = useState(0);

  // "回到现场" from the feedback inbox: reconstruct the in-app location from a
  // note's structured context (this is a SPA — the saved URL is always /app, so
  // we navigate by view + dataset/conversation, not by href).
  const jumpTo = (t: { view?: string; datasetId?: number | null; conversationId?: number | null }) => {
    if (t.datasetId != null) { setFocusDataset({ id: t.datasetId, nonce: Date.now() }); setView('datasets'); return; }
    if (t.conversationId != null) { setActiveConv(t.conversationId); setView('chat'); return; }
    if (t.view) setView(t.view as View);
  };

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
            pendingAsk={pendingAsk}
            onGoSettings={() => setView('settings')}
            onViewDataset={(id) => { setFocusDataset({ id, nonce: Date.now() }); setView('datasets'); }}
            datasetsVersion={dsVer}
          />
        </div>
        {view === 'datasets' && (
          <DatasetsView
            onAsk={(prompt, datasetId) => {
              setActiveConv(null);  // start a fresh conversation for the suggestion
              setPendingAsk({ prompt, datasetId, nonce: Date.now() });
              setView('chat');
            }}
            onGoSettings={() => setView('settings')}
            focusDataset={focusDataset}
            onBackToChat={() => setView('chat')}
            onActiveDataset={setActiveDataset}
            onDatasetsChanged={() => setDsVer((v) => v + 1)}
          />
        )}
        {view === 'algorithms' && <AlgorithmsView />}
        {view === 'templates' && <TemplatesView />}
        {view === 'skills' && <SkillsView />}
        {view === 'windtunnel' && <WindTunnelView />}
        {view === 'feedback' && <FeedbackInbox onJump={jumpTo} />}
        {view === 'settings' && <SettingsView />}
        {view === 'about' && <AboutView />}
      </main>
      <FeedbackButton view={view} conversationId={activeConv} datasetId={view === 'datasets' ? activeDataset : null} />
    </div>
  );
}
