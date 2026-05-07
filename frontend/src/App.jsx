import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import VaultPanel from './components/VaultPanel'
import { getProjects, getChats } from './api'

export default function App() {
  const [projects, setProjects]         = useState([])
  const [chats, setChats]               = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [activeChat, setActiveChat]     = useState(null)
  const [vaultOpen, setVaultOpen]       = useState(true)
  const [loading, setLoading]           = useState(true)

  useEffect(() => {
    loadProjects()
  }, [])

  useEffect(() => {
    if (activeProject) loadChats(activeProject.id)
  }, [activeProject])

  const loadProjects = async () => {
    try {
      const res = await getProjects()
      setProjects(res.data)
      if (res.data.length > 0) setActiveProject(res.data[0])
    } catch (e) {
      console.error('Failed to load projects', e)
    } finally {
      setLoading(false)
    }
  }

  const loadChats = async (projectId) => {
    try {
      const res = await getChats(projectId)
      setChats(res.data)
      if (res.data.length > 0) setActiveChat(res.data[0])
      else setActiveChat(null)
    } catch (e) {
      console.error('Failed to load chats', e)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-gray-400 text-sm">Loading DocVault AI...</div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-white overflow-hidden font-sans">
      <Sidebar
        projects={projects}
        chats={chats}
        activeProject={activeProject}
        activeChat={activeChat}
        onSelectProject={(p) => { setActiveProject(p); setActiveChat(null) }}
        onSelectChat={setActiveChat}
        onProjectsChange={loadProjects}
        onChatsChange={() => loadChats(activeProject?.id)}
        onToggleVault={() => setVaultOpen(!vaultOpen)}
        onNewChat={(chat) => { setChats(prev => [chat, ...prev]); setActiveChat(chat) }}
      />

      <ChatWindow
        chat={activeChat}
        project={activeProject}
        onChatCreated={(chat) => { setChats(prev => [chat, ...prev]); setActiveChat(chat) }}
      />

      {vaultOpen && (
        <VaultPanel
          project={activeProject}
          onClose={() => setVaultOpen(false)}
        />
      )}
    </div>
  )
}
