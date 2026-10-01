/**
 * Dashboard hub tool art. Imagine ERP tiles: one saturated squircle + white glyph.
 * Keyed by route. Lucide icons in navigation.js stay the fallback.
 */
import agent from '@/assets/hub-icons/agent.png'
import chat from '@/assets/hub-icons/chat.png'
import arena from '@/assets/hub-icons/arena.png'
import debate from '@/assets/hub-icons/debate.png'
import imageStudio from '@/assets/hub-icons/imageStudio.png'
import dataAnalyzer from '@/assets/hub-icons/dataAnalyzer.png'
import payroll from '@/assets/hub-icons/payroll.png'
import presentations from '@/assets/hub-icons/presentations.png'
import ocr from '@/assets/hub-icons/ocr.png'
import emailWriter from '@/assets/hub-icons/emailWriter.png'
import cvChecker from '@/assets/hub-icons/cvChecker.png'
import research from '@/assets/hub-icons/research.png'
import contracts from '@/assets/hub-icons/contracts.png'
import tenders from '@/assets/hub-icons/tenders.png'
import shop from '@/assets/hub-icons/shop.png'
import workflow from '@/assets/hub-icons/workflow.png'
import automateAgent from '@/assets/hub-icons/automateAgent.png'
import meetings from '@/assets/hub-icons/meetings.png'
import aiPersonas from '@/assets/hub-icons/aiPersonas.png'
import knowledgeVault from '@/assets/hub-icons/knowledgeVault.png'

export const HUB_ICONS = {
  '/agent': { src: agent, fill: '#4F46E5' },
  '/chat': { src: chat, fill: '#2563EB' },
  '/arena': { src: arena, fill: '#7C3AED' },
  '/debate': { src: debate, fill: '#F59E0B' },
  '/image-studio': { src: imageStudio, fill: '#D97706' },
  '/data-analyzer': { src: dataAnalyzer, fill: '#1D4ED8' },
  '/payroll': { src: payroll, fill: '#22C55E' },
  '/presentations': { src: presentations, fill: '#8B5CF6' },
  '/ocr': { src: ocr, fill: '#7C3AED' },
  '/email-writer': { src: emailWriter, fill: '#0EA5E9' },
  '/cv-checker': { src: cvChecker, fill: '#10B981' },
  '/research': { src: research, fill: '#06B6D4' },
  '/contracts': { src: contracts, fill: '#F43F5E' },
  '/tenders': { src: tenders, fill: '#F97316' },
  '/shop': { src: shop, fill: '#14B8A6' },
  '/workflow': { src: workflow, fill: '#3B82F6' },
  '/automate-agent': { src: automateAgent, fill: '#EF4444' },
  '/meetings': { src: meetings, fill: '#0891B2' },
  '/configs': { src: aiPersonas, fill: '#64748B' },
  '/knowledge': { src: knowledgeVault, fill: '#059669' },
}

export function hubIconFor(to) {
  if (!to) return null
  return HUB_ICONS[to] || null
}
