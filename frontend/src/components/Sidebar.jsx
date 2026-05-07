import { useState } from 'react'
import { Brain, Plus, Database, FolderOpen, MessageSquare } from 'lucide-react'
import { createProject, createChat } from '../api'

export default function Sidebar({
  projects, chats, activeProject, activeChat,
  onSelectProject, onSelectChat, onProjectsChange,
  onChatsChange, onToggleVault, onNewChat
}) {
  const [showNewProject, setShowNewProject] = useState(false)
  const [newProjectName, setNewProjectName]  = useState('')

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return
    try {
      await createProject({ name: newProjectName.trim() })
      setNewProjectName('')
      setShowNewProject(false)
      onProjectsChange()
    } catch (e) {
      console.error('Failed to create project', e)
    }
  }

  const handleNewChat = async () => {
    if (!activeProject) return
    try {
      const res = await createChat({
        title: 'New chat',
        project_id: activeProject.id
      })
      onNewChat(res.data)
    } catch (e) {
      console.error('Failed to create chat', e)
    }
  }

  return (
    <div className="w-56 flex-shrink-0 bg-gray-50 border-r border-gray-100 flex flex-col">
      {/* Logo */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <Brain size={18} className="text-gray-700" />
        <span className="font-medium text-sm text-gray-800">DocVault AI</span>
      </div>

      {/* New chat button */}
      <button
        onClick={handleNewChat}
        className="mx-2 mt-3 flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-sm text-gray-600 hover:bg-white transition-colors"
      >
        <Plus size={14} /> New chat
      </button>

      {/* Projects */}
      <div className="px-3 mt-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Projects</span>
          <button
            onClick={() => setShowNewProject(!showNewProject)}
            className="text-gray-400 hover:text-gray-600"
          >
            <Plus size={13} />
          </button>
        </div>

        {showNewProject && (
          <div className="mb-2 flex gap-1">
            <input
              className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 outline-none"
              placeholder="Project name"
              value={newProjectName}
              onChange={e => setNewProjectName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreateProject()}
              autoFocus
            />
            <button
              onClick={handleCreateProject}
              className="text-xs bg-gray-800 text-white px-2 rounded"
            >
              Add
            </button>
          </div>
        )}

        <div className="flex flex-col gap-0.5">
          {projects.map(p => (
            <button
              key={p.id}
              onClick={() => onSelectProject(p)}
              className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-left text-sm transition-colors ${
                activeProject?.id === p.id
                  ? 'bg-white text-gray-900 font-medium'
                  : 'text-gray-500 hover:bg-white hover:text-gray-800'
              }`}
            >
              <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.color }} />
              <span className="truncate">{p.name}</span>
            </button>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-gray-400 px-2 py-1">No projects yet</p>
          )}
        </div>
      </div>

      {/* Recent chats */}
      <div className="px-3 mt-4 flex-1 overflow-y-auto">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Recent chats</span>
        <div className="flex flex-col gap-0.5 mt-1">
          {chats.map(c => (
            <button
              key={c.id}
              onClick={() => onSelectChat(c)}
              className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-left text-xs transition-colors truncate ${
                activeChat?.id === c.id
                  ? 'bg-white text-gray-900'
                  : 'text-gray-500 hover:bg-white hover:text-gray-700'
              }`}
            >
              <MessageSquare size={11} className="flex-shrink-0" />
              <span className="truncate">{c.title}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Vault button */}
      <button
        onClick={onToggleVault}
        className="mx-2 mb-3 flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-xs text-gray-500 hover:bg-white transition-colors"
      >
        <Database size={13} /> Document Vault
      </button>
    </div>
  )
}
