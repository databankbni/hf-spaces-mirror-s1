import { useState, useMemo, useEffect } from 'react';
import {
  ZapIcon, SearchIcon, XIcon,
  PlusIcon, PencilIcon, Trash2Icon,
  FileTextIcon, FolderIcon,
} from 'lucide-react';
import { useSkills, useCreateSkill, useUpdateSkill, useDeleteSkill } from '../hooks/useSkills';
import { useExportableSkills, useExportDownload, useImportPreview, useImportExecute } from '../hooks/useExportImport';
import ExportDialog from '../components/ExportDialog';
import ImportDialog from '../components/ImportDialog';
import PageHeader from '../components/PageHeader';
import SkeletonCard from '../components/SkeletonCard';
import { Badge } from '../components/ui/badge';
import type { Skill } from '../types/agent';
import type { CreateSkillRequest, UpdateSkillRequest } from '../api/skills';
import type { ExportRequestItem, ConflictResolution } from '../types';
import { cn } from '@/lib/utils';

const skillTypeLabels: Record<string, string> = {
  prompt: '提示词',
  template: '模板',
  function: '函数',
};

const skillTypeColors: Record<string, string> = {
  prompt: 'opacity-60',
  template: 'opacity-60',
  function: 'opacity-60',
};

// ── 文件树面板 ──

interface FileEntry {
  path: string;
  label: string;
  isMain?: boolean;
}

function buildFileList(content: string | null, files: Record<string, string> | undefined): FileEntry[] {
  const list: FileEntry[] = [];
  list.push({ path: '__main__', label: '主文件 (content)', isMain: true });
  if (files) {
    const sorted = Object.keys(files).sort();
    for (const path of sorted) {
      const parts = path.split('/');
      const label = parts.length > 1 ? `  ${parts.slice(-1)[0]}` : path;
      list.push({ path, label });
    }
  }
  return list;
}

function FileTreePanel({
  files,
  activePath,
  onSelect,
  onAdd,
  onDelete,
  readonly,
}: {
  files: FileEntry[];
  activePath: string;
  onSelect: (path: string) => void;
  onAdd?: (name: string) => void;
  onDelete?: (path: string) => void;
  readonly?: boolean;
}) {
  const [newName, setNewName] = useState('');
  const [showAdd, setShowAdd] = useState(false);

  const handleAdd = () => {
    if (!newName.trim() || !onAdd) return;
    onAdd(newName.trim());
    setNewName('');
    setShowAdd(false);
  };

  return (
    <div className="w-48 flex-shrink-0 border-r border-foreground/10 flex flex-col">
      <div className="px-3 py-2.5 border-b border-foreground/10">
        <span className="text-[10px] font-newspaper-bold uppercase tracking-wider opacity-40">文件</span>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {files.map(entry => (
          <button
            key={entry.path}
            onClick={() => onSelect(entry.path)}
            className={cn(
              'w-full flex items-center gap-1.5 px-3 py-1.5 text-xs font-newspaper transition-colors text-left',
              activePath === entry.path
                ? 'underline font-medium'
                : 'opacity-60 hover:opacity-80',
            )}
          >
            {entry.isMain ? (
              <FileTextIcon className="w-3 h-3 flex-shrink-0" />
            ) : (
              <span className="w-3 h-3 flex-shrink-0" />
            )}
            <span className="truncate font-mono">{entry.label}</span>
            {!entry.isMain && !readonly && onDelete && (
              <XIcon
                className="w-3 h-3 ml-auto opacity-0 group-hover:opacity-100 flex-shrink-0"
                onClick={e => { e.stopPropagation(); onDelete(entry.path); }}
              />
            )}
          </button>
        ))}
      </div>
      {!readonly && onAdd && (
        <div className="border-t border-foreground/10 p-2">
          {showAdd ? (
            <div className="flex gap-1">
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAdd()}
                placeholder="views/xxx.md"
                className="flex-1 px-2 py-1 text-xs border border-foreground/15 bg-transparent font-mono focus:outline-none"
                autoFocus
              />
              <button onClick={handleAdd} className="px-1.5 py-1 text-xs underline">+</button>
            </div>
          ) : (
            <button
              onClick={() => setShowAdd(true)}
              className="w-full flex items-center gap-1 px-2 py-1.5 text-xs font-newspaper opacity-60 hover:opacity-80 transition-colors"
            >
              <PlusIcon className="w-3 h-3" /> 新建文件
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── 技能表单弹窗 ──

function SkillFormModal({
  initial,
  onClose,
  onSaved,
}: {
  initial?: Skill | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const createMutation = useCreateSkill();
  const updateMutation = useUpdateSkill();
  const isEdit = !!initial;

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [skillType, setSkillType] = useState('prompt');
  const [content, setContent] = useState('');
  const [configStr, setConfigStr] = useState('{}');
  const [files, setFiles] = useState<Record<string, string>>({});
  const [activePath, setActivePath] = useState('__main__');

  useEffect(() => {
    if (initial) {
      setName(initial.name);
      setDescription(initial.description || '');
      setSkillType(initial.skill_type);
      setContent(initial.content || '');
      setConfigStr(JSON.stringify(initial.config || {}, null, 2));
      setFiles(initial.files || {});
    } else {
      setName('');
      setDescription('');
      setSkillType('prompt');
      setContent('');
      setConfigStr('{}');
      setFiles({});
    }
    setActivePath('__main__');
  }, [initial]);

  const fileList = buildFileList(content, files);

  const activeContent = activePath === '__main__'
    ? content
    : (files[activePath] || '');

  const setActiveContent = (val: string) => {
    if (activePath === '__main__') {
      setContent(val);
    } else {
      setFiles(prev => ({ ...prev, [activePath]: val }));
    }
  };

  const handleAddFile = (name: string) => {
    setFiles(prev => ({ ...prev, [name]: '' }));
    setActivePath(name);
  };

  const handleDeleteFile = (path: string) => {
    setFiles(prev => {
      const next = { ...prev };
      delete next[path];
      return next;
    });
    if (activePath === path) setActivePath('__main__');
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    let config: Record<string, unknown> = {};
    try { config = JSON.parse(configStr); } catch { /* ignore */ }

    const payload = { name, description, skill_type: skillType, content, config, files };
    if (isEdit && initial) {
      await updateMutation.mutateAsync({ id: initial.id, data: payload as UpdateSkillRequest });
    } else {
      await createMutation.mutateAsync(payload as CreateSkillRequest);
    }
    onSaved();
  };

  const pending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative border border-foreground/20 w-[900px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-foreground/15">
          <h2 className="text-base font-newspaper-bold">{isEdit ? '编辑技能' : '创建技能'}</h2>
          <button onClick={onClose} className="p-2 hover:opacity-60 transition-opacity">
            <XIcon className="w-4 h-4 opacity-60" />
          </button>
        </div>

        {/* Body: 左侧文件树 + 右侧编辑区 */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          <FileTreePanel
            files={fileList}
            activePath={activePath}
            onSelect={setActivePath}
            onAdd={handleAddFile}
            onDelete={handleDeleteFile}
          />

          <div className="flex-1 flex flex-col overflow-y-auto p-5 gap-4">
            {activePath === '__main__' ? (
              <>
                {/* 主文件区域：基本信息 + content */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-newspaper-bold opacity-40 mb-1.5 block">技能名称 *</label>
                    <input value={name} onChange={e => setName(e.target.value)} placeholder="如：代码审查专家"
                      className="w-full px-3 py-2 border border-foreground/15 bg-transparent text-sm font-newspaper focus:outline-none" />
                  </div>
                  <div>
                    <label className="text-xs font-newspaper-bold opacity-40 mb-1.5 block">技能类型</label>
                    <div className="flex gap-2">
                      {Object.entries(skillTypeLabels).map(([val, label]) => (
                        <button key={val} onClick={() => setSkillType(val)}
                          className={`px-3 py-1.5 text-xs border border-foreground/15 font-newspaper transition-all ${skillType === val ? 'underline font-medium' : 'opacity-60 hover:opacity-80'}`}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <div>
                  <label className="text-xs font-newspaper-bold opacity-40 mb-1.5 block">描述</label>
                  <input value={description} onChange={e => setDescription(e.target.value)} placeholder="技能的简要说明"
                    className="w-full px-3 py-2 border border-foreground/15 bg-transparent text-sm font-newspaper focus:outline-none" />
                </div>
                <div>
                  <label className="text-xs font-newspaper-bold opacity-40 mb-1.5 block">主内容 (content)</label>
                  <textarea value={content} onChange={e => setContent(e.target.value)} rows={16} placeholder="技能的提示词模板或内容..."
                    className="w-full px-3 py-2 border border-foreground/15 bg-transparent text-sm font-mono resize-none focus:outline-none" />
                </div>
                <div>
                  <label className="text-xs font-newspaper-bold opacity-40 mb-1.5 block">配置（JSON）</label>
                  <textarea value={configStr} onChange={e => setConfigStr(e.target.value)} rows={3}
                    className="w-full px-3 py-2 border border-foreground/15 bg-transparent text-xs font-mono resize-none focus:outline-none" />
                </div>
              </>
            ) : (
              <>
                {/* 子文件编辑 */}
                <div>
                  <label className="text-xs font-newspaper-bold opacity-40 mb-1.5 block">
                    文件: <span className="font-mono">{activePath}</span>
                  </label>
                  <textarea
                    value={activeContent}
                    onChange={e => setActiveContent(e.target.value)}
                    rows={24}
                    placeholder={`输入 ${activePath} 的内容...`}
                    className="w-full px-3 py-2 border border-foreground/15 bg-transparent text-sm font-mono resize-none focus:outline-none"
                  />
                </div>
              </>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-5 border-t border-foreground/15">
          <button onClick={onClose} className="px-4 py-2 text-sm font-newspaper opacity-60 hover:opacity-80 transition-opacity underline">取消</button>
          <button onClick={handleSubmit} disabled={pending || !name.trim()}
            className="px-4 py-2 text-sm font-newspaper-bold hover:opacity-80 transition-opacity disabled:opacity-30 underline">
            {pending ? '保存中...' : isEdit ? '保存' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 详情弹窗 ──

function SkillDetailModal({ skill, onClose, onEdit }: { skill: Skill | null; onClose: () => void; onEdit: () => void }) {
  const [activePath, setActivePath] = useState('__main__');

  useEffect(() => {
    setActivePath('__main__');
  }, [skill?.id]);

  if (!skill) return null;

  const fileList = buildFileList(skill.content, skill.files);
  const activeContent = activePath === '__main__'
    ? (skill.content || '')
    : ((skill.files && skill.files[activePath]) || '');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative border border-foreground/20 w-[900px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between p-5 border-b border-foreground/15">
          <div className="flex items-center gap-3">
            <ZapIcon className="w-5 h-5 opacity-60" />
            <div>
              <h2 className="text-base font-newspaper-bold">{skill.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <Badge className={skillTypeColors[skill.skill_type] || 'opacity-60'}>
                  {skillTypeLabels[skill.skill_type] || skill.skill_type}
                </Badge>
                <span className="text-[10px] opacity-40 font-mono">id: {skill.id?.slice(0, 8)}</span>
                {skill.files && Object.keys(skill.files).length > 0 && (
                  <span className="text-[10px] opacity-40">
                    {Object.keys(skill.files).length} 个附加文件
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={onEdit} className="p-2 hover:opacity-60 transition-opacity" title="编辑">
              <PencilIcon className="w-4 h-4 opacity-60" />
            </button>
            <button onClick={onClose} className="p-2 hover:opacity-60 transition-opacity">
              <XIcon className="w-4 h-4 opacity-60" />
            </button>
          </div>
        </div>

        {/* Body: 左侧文件树 + 右侧内容 */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          <FileTreePanel
            files={fileList}
            activePath={activePath}
            onSelect={setActivePath}
            readonly
          />

          <div className="flex-1 overflow-y-auto p-5">
            {skill.description && activePath === '__main__' && (
              <div className="mb-4">
                <span className="text-xs font-newspaper-bold opacity-40 block mb-1">技能描述</span>
                <p className="text-sm font-newspaper leading-relaxed">{skill.description}</p>
              </div>
            )}
            <div>
              <span className="text-xs font-newspaper-bold opacity-40 block mb-2">
                {activePath === '__main__' ? '技能内容' : activePath}
              </span>
              <div className="border border-foreground/10 p-4 text-xs opacity-60 font-mono leading-relaxed max-h-[60vh] overflow-y-auto whitespace-pre-wrap">
                {activeContent || '（空）'}
              </div>
            </div>
            {activePath === '__main__' && skill.config && Object.keys(skill.config).length > 0 && (
              <div className="mt-4">
                <span className="text-xs font-newspaper-bold opacity-40 block mb-2">配置</span>
                <pre className="border border-foreground/10 p-3 text-xs opacity-60 font-mono leading-relaxed overflow-x-auto">
                  {JSON.stringify(skill.config, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 主页面 ──

export default function SkillsPage() {
  const { data: skillsData, isLoading } = useSkills();
  const deleteMutation = useDeleteSkill();
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState<string | 'all'>('all');
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [formSkill, setFormSkill] = useState<Skill | null | undefined>(undefined); // undefined=closed, null=create, Skill=edit

  // 导出导入
  const [exportOpen, setExportOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const { data: exportableSkills, isLoading: exportLoading } = useExportableSkills();
  const exportDownload = useExportDownload();
  const importPreview = useImportPreview();
  const importExecute = useImportExecute();

  const allSkills: Skill[] = skillsData?.items || [];

  const skillTypes = useMemo(() => {
    const types = new Set(allSkills.map(s => s.skill_type));
    return Array.from(types);
  }, [allSkills]);

  const filtered = useMemo(() => {
    let items = allSkills;
    if (filterType !== 'all') {
      items = items.filter(s => s.skill_type === filterType);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(s =>
        s.name.toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q)
      );
    }
    return items;
  }, [allSkills, search, filterType]);

  const handleDelete = async (skill: Skill) => {
    if (!confirm(`确定删除技能「${skill.name}」？`)) return;
    await deleteMutation.mutateAsync(skill.id);
    if (selectedSkill?.id === skill.id) setSelectedSkill(null);
  };

  return (
    <div data-cmp="SkillsPage" className="min-h-screen newspaper-bg">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12 py-6 md:py-10">
        {/* Header */}
        <PageHeader
          backTo="/"
          brand="Agent 世界"
          brandIcon={<ZapIcon className="w-4 h-4" />}
          title="技能库"
          description="管理可复用的技能模块，Agent 绑定后即可使用"
          actions={
            <>
              <div className="text-sm font-newspaper opacity-60">
                共 <span className="font-newspaper-bold">{allSkills.length}</span> 个技能
              </div>
              <button className="text-sm font-newspaper underline hover:opacity-60 transition-opacity" onClick={() => setExportOpen(true)}>
                导出
              </button>
              <button className="text-sm font-newspaper underline hover:opacity-60 transition-opacity" onClick={() => setImportOpen(true)}>
                导入
              </button>
              <button className="text-sm font-newspaper-bold underline hover:opacity-60 transition-opacity" onClick={() => setFormSkill(null)}>
                创建技能
              </button>
            </>
          }
        />

        {/* Search + Type filter */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 opacity-40" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索技能..."
              className="w-full pl-10 pr-4 py-2.5 border border-foreground/15 bg-transparent text-sm font-newspaper placeholder:opacity-30 focus:outline-none" />
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setFilterType('all')}
              className={`px-3 py-1.5 text-xs border border-foreground/15 font-newspaper transition-all ${filterType === 'all' ? 'underline font-medium' : 'opacity-60 hover:opacity-80'}`}>
              全部
            </button>
            {skillTypes.map(type => (
              <button key={type}
                onClick={() => setFilterType(type)}
                className={`px-3 py-1.5 text-xs border border-foreground/15 font-newspaper transition-all ${filterType === type ? 'underline font-medium' : 'opacity-60 hover:opacity-80'}`}>
                {skillTypeLabels[type] || type}
              </button>
            ))}
          </div>
        </div>

        {isLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        )}

        {!isLoading && allSkills.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-16 h-16 border border-foreground/15 flex items-center justify-center">
              <ZapIcon className="w-8 h-8 opacity-40" />
            </div>
            <div className="text-center">
              <p className="text-base font-newspaper-bold mb-1">暂无技能</p>
              <p className="text-sm font-newspaper opacity-40">点击「创建技能」添加你的第一个技能</p>
            </div>
          </div>
        )}

        {!isLoading && filtered.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filtered.map(skill => (
              <div key={skill.id}
                className="border border-foreground/15 p-4 transition-all duration-200 group relative">
                <button onClick={() => setSelectedSkill(skill)} className="text-left w-full">
                  <div className="flex items-start justify-between mb-2">
                    <ZapIcon className="w-4 h-4 opacity-60" />
                  </div>
                  <h3 className="text-sm font-newspaper-bold mb-1">{skill.name}</h3>
                  <div className="mb-2">
                    <Badge className={skillTypeColors[skill.skill_type] || 'opacity-60'}>
                      {skillTypeLabels[skill.skill_type] || skill.skill_type}
                    </Badge>
                  </div>
                  <p className="text-xs font-newspaper opacity-40 leading-relaxed line-clamp-2">
                    {skill.description || '暂无描述'}
                  </p>
                  {skill.files && Object.keys(skill.files).length > 0 && (
                    <div className="mt-2 flex items-center gap-1 text-[10px] opacity-30">
                      <FolderIcon className="w-3 h-3" />
                      {Object.keys(skill.files).length} 个文件
                    </div>
                  )}
                </button>
                <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                  <button onClick={() => setFormSkill(skill)} className="p-1.5 hover:opacity-60" title="编辑">
                    <PencilIcon className="w-3 h-3 opacity-60" />
                  </button>
                  <button onClick={() => handleDelete(skill)} className="p-1.5 hover:opacity-60" title="删除">
                    <Trash2Icon className="w-3 h-3 opacity-40" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <SkillDetailModal
        skill={selectedSkill}
        onClose={() => setSelectedSkill(null)}
        onEdit={() => { setFormSkill(selectedSkill); setSelectedSkill(null); }}
      />

      {formSkill !== undefined && (
        <SkillFormModal
          initial={formSkill}
          onClose={() => setFormSkill(undefined)}
          onSaved={() => setFormSkill(undefined)}
        />
      )}

      {/* 导出对话框 */}
      <ExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        type="skill"
        title="导出技能"
        items={exportableSkills || []}
        loading={exportLoading}
        exporting={exportDownload.isPending}
        onExport={(items: ExportRequestItem[]) => {
          exportDownload.mutate({ items, filename: 'skills_export.zip' }, {
            onSuccess: () => setExportOpen(false),
          })
        }}
      />

      {/* 导入对话框 */}
      <ImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        type="skill"
        previewResult={importPreview.data?.data ?? null}
        previewing={importPreview.isPending}
        executeResult={importExecute.data?.data ?? null}
        executing={importExecute.isPending}
        onPreview={(file: File) => importPreview.mutate(file)}
        onExecute={(file: File, resolutions: ConflictResolution[]) => {
          importExecute.mutate({ file, resolutions }, {
            onSuccess: () => {
              importPreview.reset()
            },
          })
        }}
      />
    </div>
  );
}
