import { useTranslation } from 'react-i18next'

function BulletSection({ title, items }) {
  if (!items?.length) return null
  return (
    <section className="space-y-1.5 min-w-0">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="list-disc ps-5 text-sm space-y-1" dir="auto">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </section>
  )
}

export default function CvFindings({ strengths, gaps }) {
  const { t } = useTranslation('cvChecker')
  const s = Array.isArray(strengths) ? strengths : []
  const g = Array.isArray(gaps) ? gaps : []
  if (!s.length && !g.length) return null

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <BulletSection title={t('strengths')} items={s} />
      <BulletSection title={t('gaps')} items={g} />
    </div>
  )
}
