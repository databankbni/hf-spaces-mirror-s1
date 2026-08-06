import { createPortal } from 'react-dom';
import {
  XIcon, BotIcon, ZapIcon, BrainIcon, WrenchIcon, BookOpenIcon,
  ShieldIcon, ClockIcon, ThermometerIcon, HashIcon, TagIcon, EditIcon,
  UsersIcon,
} from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import type { Agent, AgentMemory } from '../types/agent';

interface AgentCardProps {
  agent?: Agent | null;
  onClose?: () => void;
  compact?: boolean;
  /** 群聊内角色 */
  groupRole?: 'lead' | 'participant';
  /** 加入群聊时间 */
  joinedAt?: string;
  /** Agent 在项目中的记忆（可能有多条，按 slug 分类） */
  memories?: AgentMemory[] | null;
  /** 点击编辑回调 */
  onEdit?: () => void;
}

const toolTypeLabels: Record<string, string> = {
  builtin: '内置',
  function: '函数',
  api: 'API',
};

const skillTypeLabels: Record<string, string> = {
  prompt: '提示词',
  template: '模板',
  function: '函数',
};

const groupRoleConfig = {
  lead: { label: '负责人', barClass: 'bg-foreground/50', badgeClass: 'text-foreground/70' },
  participant: { label: '参与者', barClass: 'bg-foreground/20', badgeClass: 'text-foreground/50' },
};

function formatDate(dateStr?: string) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatConfigEntries(config: Record<string, unknown> | undefined): { key: string; value: string }[] {
  if (!config || Object.keys(config).length === 0) return [];
  return Object.entries(config)
    .filter(([, v]) => v != null && v !== '')
    .map(([key, value]) => ({
      key,
      value: typeof value === 'object' ? JSON.stringify(value) : String(value),
    }));
}

export default function AgentCard({
  agent = null,
  onClose = () => {},
  compact = false,
  groupRole,
  joinedAt,
  memories,
  onEdit,
}: AgentCardProps) {
  const visible = agent !== null;

  if (compact && agent) {
    return (
      <div data-cmp="AgentCard" className="flex items-center gap-2 p-2 border border-foreground/10 cursor-pointer transition-colors">
        <div className="w-8 h-8 flex items-center justify-center text-sm flex-shrink-0 opacity-70">
          {agent.avatar || '🤖'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-newspaper-bold text-foreground truncate">{agent.name}</span>
            {groupRole && groupRoleConfig[groupRole] && (
              <span className="text-[10px] font-newspaper opacity-50 flex-shrink-0">
                [{groupRoleConfig[groupRole].label}]
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            {agent.description && (
              <span className="text-[10px] font-newspaper opacity-40 truncate">{agent.description}</span>
            )}
          </div>
        </div>
        <div className="text-xs font-newspaper opacity-40 flex-shrink-0">{agent.llm_config?.model || '-'}</div>
      </div>
    );
  }

  const modalContent = (
    <div
      data-cmp="AgentCard"
      className={`fixed inset-0 z-[9999] flex items-center justify-center transition-all duration-300 ${visible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}
    >
      <div className={`absolute inset-0 bg-foreground/20 backdrop-blur-sm transition-opacity duration-300 ${visible ? 'opacity-100' : 'opacity-0'}`} onClick={onClose} />
      <div
        className={`relative newspaper-bg border border-foreground/20 w-[580px] max-w-[90vw] max-h-[85vh] flex flex-col transition-all duration-300 ease-out ${visible ? 'scale-100 opacity-100' : 'scale-95 opacity-0'}`}
      >
        {agent && (
          <>
            {groupRole && groupRoleConfig[groupRole] && (
              <div className="h-px bg-foreground/20" />
            )}

            {/* Header */}
            <div className="flex items-start justify-between p-4 border-b border-foreground/10 flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 flex items-center justify-center text-xl opacity-70">
                  {agent.avatar || '🤖'}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-newspaper-bold text-foreground">{agent.name}</h2>
                    {groupRole && groupRoleConfig[groupRole] && (
                      <span className="text-[10px] font-newspaper opacity-50">
                        [{groupRoleConfig[groupRole].label}]
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    {agent.is_active === false && (
                      <span className="text-[10px] font-newspaper opacity-40">/ 已停用</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1">
                {onEdit && (
                  <button onClick={onEdit} className="p-1.5 opacity-40 hover:opacity-70 transition-opacity" title="编辑">
                    <EditIcon className="w-4 h-4" />
                  </button>
                )}
                <button onClick={onClose} className="p-1.5 opacity-40 hover:opacity-70 transition-opacity">
                  <XIcon className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Tabs */}
            <Tabs defaultValue="overview" className="flex-1 flex flex-col min-h-0">
              <div className="px-4 pt-2.5 flex-shrink-0">
                <TabsList className="w-full">
                  <TabsTrigger value="overview" className="flex-1 gap-1.5 font-newspaper">
                    <BotIcon className="w-3.5 h-3.5" />概览
                  </TabsTrigger>
                  <TabsTrigger value="equipment" className="flex-1 gap-1.5 font-newspaper">
                    <WrenchIcon className="w-3.5 h-3.5" />装备
                    {(agent.tools?.length || 0) + (agent.skills?.length || 0) > 0 && (
                      <span className="ml-0.5 text-[10px] font-newspaper opacity-50">
                        ({(agent.tools?.length || 0) + (agent.skills?.length || 0)})
                      </span>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="memory" className="flex-1 gap-1.5 font-newspaper">
                    <BookOpenIcon className="w-3.5 h-3.5" />记忆
                  </TabsTrigger>
                </TabsList>
              </div>

              <div className="flex-1 overflow-y-auto">
                {/* Tab 1: Overview */}
                <TabsContent value="overview" className="p-4 flex flex-col gap-3">
                  {agent.description && (
                    <Section icon={<BotIcon className="w-4 h-4 opacity-40" />} title="Agent 简介">
                      <p className="text-sm font-newspaper opacity-60 leading-relaxed">{agent.description}</p>
                    </Section>
                  )}

                  {groupRole && groupRoleConfig[groupRole] && (
                    <Section icon={<UsersIcon className="w-4 h-4 opacity-40" />} title="群聊角色">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-newspaper opacity-50">
                          {groupRoleConfig[groupRole].label}
                        </span>
                        {joinedAt && (
                          <span className="text-xs font-newspaper opacity-40">加入于 {formatDate(joinedAt)}</span>
                        )}
                      </div>
                    </Section>
                  )}

                  {agent.capabilities?.length > 0 && (
                    <Section icon={<ZapIcon className="w-4 h-4 opacity-40" />} title="核心能力">
                      <div className="flex flex-wrap gap-1">
                        {agent.capabilities.map(cap => (
                          <span key={cap} className="text-[11px] font-newspaper opacity-50">
                            {cap}
                          </span>
                        ))}
                      </div>
                    </Section>
                  )}

                  <Section icon={<BrainIcon className="w-4 h-4 opacity-40" />} title="模型配置">
                    <div className="flex flex-wrap gap-1.5">
                      <ConfigChip label="模型" value={agent.llm_config?.model || '未设置'} />
                      {agent.llm_config?.temperature != null && (
                        <ConfigChip label="温度" value={String(agent.llm_config.temperature)} icon={<ThermometerIcon className="w-3 h-3" />} />
                      )}
                      {agent.llm_config?.max_tokens != null && (
                        <ConfigChip label="最大Token" value={String(agent.llm_config.max_tokens)} icon={<HashIcon className="w-3 h-3" />} />
                      )}
                    </div>
                  </Section>

                  {agent.system_prompt && (
                    <Section icon={<ShieldIcon className="w-4 h-4 opacity-40" />} title="系统提示词">
                      <div className="border border-foreground/10 p-2.5 text-xs font-newspaper opacity-60 font-mono leading-relaxed whitespace-pre-wrap">
                        {agent.system_prompt}
                      </div>
                    </Section>
                  )}

                  {!groupRole && joinedAt && (
                    <Section icon={<ClockIcon className="w-4 h-4 opacity-40" />} title="加入时间">
                      <p className="text-xs font-newspaper opacity-40">{formatDate(joinedAt)}</p>
                    </Section>
                  )}
                </TabsContent>

                {/* Tab 2: Equipment (Tools + Skills) */}
                <TabsContent value="equipment" className="p-4 flex flex-col gap-3">
                  <Section icon={<WrenchIcon className="w-4 h-4 opacity-40" />} title={`工具${agent.tools?.length ? ` (${agent.tools.length})` : ''}`}>
                    {agent.tools?.length ? (
                      <div className="flex flex-col gap-1.5">
                        {agent.tools.map(tool => (
                          <ToolItem
                            key={tool.id}
                            name={tool.name}
                            type={tool.tool_type}
                            typeLabel={toolTypeLabels[tool.tool_type] || tool.tool_type}
                            description={tool.description}
                            config={tool.config}
                            icon={<WrenchIcon className="w-3.5 h-3.5 opacity-40" />}
                          />
                        ))}
                      </div>
                    ) : (
                      <EmptyState text="暂未绑定工具" />
                    )}
                  </Section>

                  <Section icon={<ZapIcon className="w-4 h-4 opacity-40" />} title={`技能${agent.skills?.length ? ` (${agent.skills.length})` : ''}`}>
                    {agent.skills?.length ? (
                      <div className="flex flex-col gap-1.5">
                        {agent.skills.map(skill => (
                          <ToolItem
                            key={skill.id}
                            name={skill.name}
                            type={skill.skill_type}
                            typeLabel={skillTypeLabels[skill.skill_type] || skill.skill_type}
                            description={skill.description}
                            config={skill.config}
                            icon={<ZapIcon className="w-3.5 h-3.5 opacity-40" />}
                          />
                        ))}
                      </div>
                    ) : (
                      <EmptyState text="暂未绑定技能" />
                    )}
                  </Section>
                </TabsContent>

                {/* Tab 3: Memory */}
                <TabsContent value="memory" className="p-4 flex flex-col gap-3">
                  {memories && memories.length > 0 ? (
                    <>
                      {memories.map((memory) => (
                        <div key={memory.id} className="flex flex-col gap-2">
                          {memory.slug && memory.slug !== 'default' && (
                            <div className="text-xs font-newspaper-bold text-foreground/70">
                              {memory.slug}
                            </div>
                          )}
                          {memory.tags?.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {memory.tags.map(tag => (
                                <span key={tag} className="text-[10px] font-newspaper flex items-center gap-1 opacity-50">
                                  <TagIcon className="w-2.5 h-2.5" />{tag}
                                </span>
                              ))}
                            </div>
                          )}
                          <Section icon={<BookOpenIcon className="w-4 h-4 opacity-40" />} title="项目笔记">
                            <div className="border border-foreground/10 p-2.5 text-sm font-newspaper opacity-60 leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap">
                              {memory.content}
                            </div>
                          </Section>
                          <p className="text-[10px] font-newspaper opacity-30 text-right">
                            最后更新：{formatDate(memory.updated_at)}
                          </p>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-10 gap-3">
                      <BookOpenIcon className="w-8 h-8 opacity-20" />
                      <p className="text-sm font-newspaper opacity-40">该 Agent 暂无项目记忆</p>
                      <p className="text-xs font-newspaper opacity-30">随着协作推进，Agent 会积累项目相关知识</p>
                    </div>
                  )}
                </TabsContent>
              </div>
            </Tabs>
          </>
        )}
      </div>
    </div>
  );

  return visible ? createPortal(modalContent, document.body) : null;
}

/* ---------- 子组件 ---------- */

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        {icon}
        <span className="text-sm font-newspaper-bold text-foreground">{title}</span>
      </div>
      {children}
    </div>
  );
}

function ConfigChip({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1 border border-foreground/10 px-2 py-1 text-[11px] font-newspaper">
      {icon}
      <span className="opacity-40">{label}:</span>
      <span className="font-mono opacity-60">{value}</span>
    </div>
  );
}

function ToolItem({
  name,
  type,
  typeLabel,
  description,
  config,
  icon,
}: {
  name: string;
  type: string;
  typeLabel: string;
  description: string | null;
  config: Record<string, unknown> | undefined;
  icon: React.ReactNode;
}) {
  const configEntries = formatConfigEntries(config);

  return (
    <div className="flex items-start gap-2 p-2 border border-foreground/10">
      <div className="w-6 h-6 flex items-center justify-center flex-shrink-0 mt-0.5 opacity-50">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-newspaper-bold text-foreground">{name}</span>
          <span className="text-[10px] font-newspaper opacity-40">
            [{typeLabel}]
          </span>
        </div>
        {description && (
          <p className="text-[11px] font-newspaper opacity-40 mt-0.5 line-clamp-2">{description}</p>
        )}
        {configEntries.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {configEntries.map(({ key, value }) => (
              <span key={key} className="text-[10px] font-newspaper opacity-40 font-mono">
                {key}={value}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center py-4">
      <p className="text-xs font-newspaper opacity-40 italic">{text}</p>
    </div>
  );
}
