import { useState, useEffect } from 'react';
import {
  XIcon, PlusIcon, TagIcon, UploadIcon, PackageIcon, SparklesIcon,
  UsersIcon, BoxesIcon, FileTextIcon, LayersIcon, ChevronRightIcon
} from 'lucide-react';
import { useCreateProject, useUpdateProject, useImportProject } from '../hooks/useProjects';
import { useTemplateList, useApplyTemplate } from '../hooks/useTemplates';
import { PAPER_COVER_OPTIONS } from '../lib/coverColor';
import type { ProjectListItem, Project, ProjectStatus } from '../types';
import type { TemplateSummary } from '../api/templates';

interface CreateProjectModalProps {
  open?: boolean;
  onClose?: () => void;
  onCreated?: (id: string) => void;
  onUpdated?: (id: string) => void;
  project?: ProjectListItem | Project;
}

/** 封面颜色选项：报纸色系，与 themes/colors.ts 的 5 个色系对应 */
const COVER_COLORS = PAPER_COVER_OPTIONS;

const STATUS_OPTIONS: { value: ProjectStatus; label: string }[] = [
  { value: 'active', label: '进行中' },
  { value: 'paused', label: '已暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已归档' },
];

export default function CreateProjectModal({
  open = false,
  onClose = () => {},
  onCreated = () => {},
  onUpdated = () => {},
  project,
}: CreateProjectModalProps) {
  const isEditing = !!project;

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tagInput, setTagInput] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [selectedColor, setSelectedColor] = useState(COVER_COLORS[0].value);
  const [status, setStatus] = useState<ProjectStatus>('active');
  const [createMode, setCreateMode] = useState<'blank' | 'import' | 'template'>('blank');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateSummary | null>(null);

  const createProjectMutation = useCreateProject();
  const updateProjectMutation = useUpdateProject();
  const importProjectMutation = useImportProject();
  const applyTemplateMutation = useApplyTemplate();
  const { data: templates = [], isLoading: templatesLoading } = useTemplateList();

  // 编辑模式：预填充表单
  useEffect(() => {
    if (project && open) {
      setName(project.name || '');
      setDescription(project.description || '');
      setTags(project.tags || []);
      setSelectedColor(project.cover_color || COVER_COLORS[0].value);
      setStatus(project.status || 'active');
      setCreateMode('blank');
      setImportFile(null);
      setSelectedTemplate(null);
    } else if (!open) {
      // 关闭时重置表单
      setName('');
      setDescription('');
      setTags([]);
      setSelectedColor(COVER_COLORS[0].value);
      setStatus('active');
      setCreateMode('blank');
      setImportFile(null);
      setSelectedTemplate(null);
    }
  }, [project, open]);

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !tags.includes(t)) {
      setTags([...tags, t]);
    }
    setTagInput('');
  };

  const removeTag = (tag: string) => {
    setTags(tags.filter(t => t !== tag));
  };

  const handleSubmit = async () => {
    if (!isEditing && createMode === 'import') {
      if (!importFile) return;
      try {
        const imported = await importProjectMutation.mutateAsync(importFile);
        onCreated(imported.id);
        onClose();
      } catch (error) {
        console.error('Failed to import project:', error);
      }
      return;
    }

    if (!isEditing && createMode === 'template') {
      if (!selectedTemplate || !name.trim()) return;
      try {
        const result = await applyTemplateMutation.mutateAsync({
          template_id: selectedTemplate.template_id,
          project_name: name.trim(),
          project_description: description.trim() || undefined,
          cover_color: selectedColor,
          project_tags: tags.length > 0 ? tags : undefined,
        });
        onCreated(result.data.project_id);
        onClose();
      } catch (error) {
        console.error('Failed to apply template:', error);
      }
      return;
    }

    if (!name.trim()) return;
    try {
      if (isEditing && project) {
        const updated = await updateProjectMutation.mutateAsync({
          id: project.id,
          data: {
            name: name.trim(),
            description: description.trim(),
            tags,
            cover_color: selectedColor,
            status,
          },
        });
        onUpdated(updated.id);
      } else {
        const proj = await createProjectMutation.mutateAsync({
          name: name.trim(),
          description: description.trim(),
          tags,
          cover_color: selectedColor,
        });
        onCreated(proj.id);
      }
      onClose();
    } catch (error) {
      console.error('Failed to save project:', error);
    }
  };

  const isLoading = createProjectMutation.isPending || updateProjectMutation.isPending || importProjectMutation.isPending || applyTemplateMutation.isPending;
  const canSubmit = isEditing || createMode === 'blank'
    ? !!name.trim()
    : createMode === 'import'
      ? !!importFile
      : !!selectedTemplate && !!name.trim();

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-200 ${open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}>
      <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={onClose} />
      <div className={`relative newspaper-bg border border-foreground/20 w-[600px] max-h-[85vh] overflow-y-auto transition-all duration-200 ${open ? 'scale-100' : 'scale-95'}`} onClick={e => e.stopPropagation()}>
        {/* Newspaper masthead header */}
        <div className="px-6 pt-5 pb-3 border-b border-foreground/10">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-newspaper-bold text-foreground tracking-wide">{isEditing ? '编辑项目' : '创建新项目'}</h2>
            <button onClick={onClose} className="p-1.5 opacity-40 hover:opacity-70 transition-opacity">
              <XIcon className="w-4 h-4" />
            </button>
          </div>
          <div className="mt-2 h-px bg-foreground/20" />
          <div className="mt-1 h-px bg-foreground/10" />
        </div>

        {/* Preview */}
        <div className={`mx-6 mt-5 h-24 bg-gradient-to-br ${selectedColor} flex items-center justify-center border border-foreground/10`}>
          <span className="text-foreground/80 text-lg font-newspaper-bold tracking-wide">
            {name || (isEditing ? project?.name : createMode === 'template' ? '从模板创建' : '新项目')}
          </span>
        </div>

        <div className="p-6 flex flex-col gap-4">
          {!isEditing && (
            <div>
              <label className="text-xs font-newspaper opacity-40 mb-2 block">创建方式</label>
              <div className="grid grid-cols-3 gap-2 border border-foreground/10 p-1">
                <button
                  onClick={() => setCreateMode('blank')}
                  className={`flex items-center justify-center gap-2 px-3 py-2 text-xs font-newspaper transition-all ${createMode === 'blank' ? 'border border-foreground/20 text-foreground' : 'opacity-40'}`}
                >
                  <PlusIcon className="w-3.5 h-3.5" />
                  空白项目
                </button>
                <button
                  onClick={() => setCreateMode('template')}
                  className={`flex items-center justify-center gap-2 px-3 py-2 text-xs font-newspaper transition-all ${createMode === 'template' ? 'border border-foreground/20 text-foreground' : 'opacity-40'}`}
                >
                  <SparklesIcon className="w-3.5 h-3.5" />
                  从模板创建
                </button>
                <button
                  onClick={() => setCreateMode('import')}
                  className={`flex items-center justify-center gap-2 px-3 py-2 text-xs font-newspaper transition-all ${createMode === 'import' ? 'border border-foreground/20 text-foreground' : 'opacity-40'}`}
                >
                  <PackageIcon className="w-3.5 h-3.5" />
                  从资产包
                </button>
              </div>
            </div>
          )}

          {!isEditing && createMode === 'template' ? (
            <div className="flex flex-col gap-4">
              {/* 模板列表 */}
              <div>
                <label className="text-xs font-newspaper opacity-40 mb-1.5 block">选择模板</label>
                {templatesLoading ? (
                  <div className="border border-foreground/10 p-4 text-sm font-newspaper opacity-50 text-center">
                    加载中…
                  </div>
                ) : templates.length === 0 ? (
                  <div className="border border-foreground/10 p-4 text-sm font-newspaper opacity-50 text-center">
                    暂无可用模板
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 max-h-72 overflow-y-auto pr-1">
                    {templates.map(t => (
                      <button
                        key={t.template_id}
                        onClick={() => setSelectedTemplate(t)}
                        className={`text-left border p-3 transition-all ${selectedTemplate?.template_id === t.template_id
                          ? 'border-foreground/40 bg-foreground/[0.04]'
                          : 'border-foreground/10 hover:border-foreground/20 hover:bg-foreground/[0.02]'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <div className={`w-10 h-10 bg-gradient-to-br ${t.cover_color || 'from-amber-500 to-orange-600'} flex items-center justify-center text-lg flex-shrink-0`}>
                            {t.emoji || '✨'}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-newspaper-bold text-sm text-foreground">{t.name}</span>
                              <span className="text-xs font-newspaper opacity-30">v{t.version}</span>
                            </div>
                            <p className="text-xs font-newspaper opacity-60 mt-1 line-clamp-2 leading-relaxed">{t.description}</p>
                            <div className="flex items-center gap-3 mt-2 text-xs font-newspaper opacity-50">
                              <span className="flex items-center gap-1">
                                <UsersIcon className="w-3 h-3" />
                                {t.preview?.agent_count ?? 0}
                              </span>
                              <span className="flex items-center gap-1">
                                <BoxesIcon className="w-3 h-3" />
                                {t.preview?.skill_count ?? 0}
                              </span>
                              <span className="flex items-center gap-1">
                                <LayersIcon className="w-3 h-3" />
                                {t.preview?.group_count ?? 0} 阶段
                              </span>
                              <span className="flex items-center gap-1">
                                <FileTextIcon className="w-3 h-3" />
                                {t.preview?.task_count ?? 0} 任务
                              </span>
                            </div>
                          </div>
                          {selectedTemplate?.template_id === t.template_id && (
                            <ChevronRightIcon className="w-4 h-4 opacity-60 flex-shrink-0" />
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* 选中模板的说明 */}
              {selectedTemplate && (
                <div className="border border-foreground/10 p-3 bg-foreground/[0.02]">
                  <div className="text-xs font-newspaper opacity-40 mb-1">模板将创建</div>
                  <div className="text-xs font-newspaper text-foreground/70 leading-relaxed">
                    {selectedTemplate.preview?.agent_count} 名 Agent、{selectedTemplate.preview?.skill_count} 个 Skill、
                    {selectedTemplate.preview?.group_count} 个群聊（流水线阶段）、{selectedTemplate.preview?.task_count} 个任务、
                    {selectedTemplate.preview?.resource_count} 个项目级资源
                  </div>
                  {selectedTemplate.tags.length > 0 && (
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {selectedTemplate.tags.map(tag => (
                        <span key={tag} className="font-newspaper text-xs opacity-50 border border-foreground/10 px-1.5 py-0.5">
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Color picker */}
              <div>
                <label className="text-xs font-newspaper opacity-40 mb-2 block">封面颜色</label>
                <div className="flex gap-2">
                  {COVER_COLORS.map(c => (
                    <button
                      key={c.value}
                      onClick={() => setSelectedColor(c.value)}
                      className={`w-8 h-8 bg-gradient-to-br ${c.value} transition-all ${selectedColor === c.value ? 'ring-2 ring-foreground ring-offset-2 scale-110' : 'hover:scale-105'}`}
                    />
                  ))}
                </div>
              </div>

              {/* Name */}
              <div>
                <label className="text-xs font-newspaper opacity-40 mb-1.5 block">项目名称 *</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder={`例：我的玄幻小说`}
                  className="w-full px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground placeholder:font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/30"
                />
              </div>

              {/* Description */}
              <div>
                <label className="text-xs font-newspaper opacity-40 mb-1.5 block">项目描述（可选）</label>
                <textarea
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder={`留空则使用模板默认描述`}
                  rows={2}
                  className="w-full px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground placeholder:font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/30 resize-none"
                />
              </div>

              {/* Tags */}
              <div>
                <label className="text-xs font-newspaper opacity-40 mb-1.5 block">标签</label>
                <div className="flex gap-2 mb-2 flex-wrap">
                  {tags.map(tag => (
                    <span key={tag} className="flex items-center gap-1 font-newspaper text-xs opacity-60">
                      <TagIcon className="w-3 h-3" />
                      {tag}
                      <button onClick={() => removeTag(tag)} className="ml-0.5 opacity-40 hover:opacity-70">
                        <XIcon className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    value={tagInput}
                    onChange={e => setTagInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
                    placeholder={`输入标签后按 Enter`}
                    className="flex-1 px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground placeholder:font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/30"
                  />
                  <button onClick={addTag} className="px-3 py-2 border border-foreground/15 text-sm font-newspaper opacity-50 hover:opacity-70 transition-opacity">
                    <PlusIcon className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ) : !isEditing && createMode === 'import' ? (
            <div className="flex flex-col gap-4">
              <label className="border-2 border-dashed border-foreground/20 p-6 text-center hover:border-foreground/40 transition-colors cursor-pointer">
                <UploadIcon className="w-8 h-8 mx-auto mb-3 opacity-40" />
                <div className="text-sm font-newspaper-bold text-foreground">选择项目资产包 ZIP</div>
                <div className="text-xs font-newspaper opacity-40 mt-1">当前导入选择入口已放在新建项目弹窗；后端选择性导入完成前会按现有接口全量导入。</div>
                <input
                  type="file"
                  accept=".zip,application/zip"
                  onChange={event => setImportFile(event.target.files?.[0] || null)}
                  className="hidden"
                />
              </label>
              {importFile && (
                <div className="border border-foreground/10 p-3 text-sm">
                  <div className="font-newspaper-bold text-foreground">{importFile.name}</div>
                  <div className="text-xs font-newspaper opacity-40 mt-1">{Math.ceil(importFile.size / 1024)} KB</div>
                </div>
              )}
              <div className="border border-foreground/10 p-3 text-xs font-newspaper opacity-50 leading-relaxed">
                选择性导入树会在后端 import preview/selective import 接口补齐后启用；当前按钮将使用现有导入接口创建项目。
              </div>
            </div>
          ) : (
          <>
          {/* Color picker */}
          <div>
            <label className="text-xs font-newspaper opacity-40 mb-2 block">封面颜色</label>
            <div className="flex gap-2">
              {COVER_COLORS.map(c => (
                <button
                  key={c.value}
                  onClick={() => setSelectedColor(c.value)}
                  className={`w-8 h-8 bg-gradient-to-br ${c.value} transition-all ${selectedColor === c.value ? 'ring-2 ring-foreground ring-offset-2 scale-110' : 'hover:scale-105'}`}
                />
              ))}
            </div>
          </div>

          {/* Name */}
          <div>
            <label className="text-xs font-newspaper opacity-40 mb-1.5 block">项目名称 *</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder={`例：玄幻小说创作、市场调研报告`}
              className="w-full px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground placeholder:font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/30"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-xs font-newspaper opacity-40 mb-1.5 block">项目描述</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder={`简要描述项目目标和范围`}
              rows={3}
              className="w-full px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground placeholder:font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/30 resize-none"
            />
          </div>

          {/* Status (edit mode only) */}
          {isEditing && (
            <div>
              <label className="text-xs font-newspaper opacity-40 mb-1.5 block">项目状态</label>
              <select
                value={status}
                onChange={e => setStatus(e.target.value as ProjectStatus)}
                className="w-full px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground focus:outline-none focus:border-foreground/30"
              >
                {STATUS_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          )}

          {/* Tags */}
          <div>
            <label className="text-xs font-newspaper opacity-40 mb-1.5 block">标签</label>
            <div className="flex gap-2 mb-2 flex-wrap">
              {tags.map(tag => (
                <span key={tag} className="flex items-center gap-1 font-newspaper text-xs opacity-60">
                  <TagIcon className="w-3 h-3" />
                  {tag}
                  <button onClick={() => removeTag(tag)} className="ml-0.5 opacity-40 hover:opacity-70">
                    <XIcon className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
                placeholder={`输入标签后按 Enter`}
                className="flex-1 px-3 py-2 bg-transparent border border-foreground/15 text-sm font-newspaper text-foreground placeholder:font-newspaper placeholder:opacity-30 focus:outline-none focus:border-foreground/30"
              />
              <button onClick={addTag} className="px-3 py-2 border border-foreground/15 text-sm font-newspaper opacity-50 hover:opacity-70 transition-opacity">
                <PlusIcon className="w-4 h-4" />
              </button>
            </div>
          </div>
          </>
          )}
        </div>

        <div className="px-6 pb-6 flex gap-4 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm font-newspaper opacity-40 hover:opacity-70 transition-opacity">
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || isLoading}
            className="px-5 py-2 text-sm font-newspaper-bold text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {isLoading ? '保存中...' : isEditing ? '保存修改' : createMode === 'import' ? '导入项目' : createMode === 'template' ? '从模板创建' : '创建项目'}
          </button>
        </div>
      </div>
    </div>
  );
}
