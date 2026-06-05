import { MeetingDetailView } from '@/components/meetings/meeting-detail-view'

interface Props {
  params: { id: string }
}

export default function MeetingDetailPage({ params }: Props) {
  return (
    <main className="container mx-auto px-4 py-6 max-w-6xl">
      <MeetingDetailView meetingId={params.id} />
    </main>
  )
}
