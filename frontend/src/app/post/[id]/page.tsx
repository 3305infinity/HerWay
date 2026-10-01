import React from 'react';
import PostDetail from '@/components/PostDetail';

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <div className="h-full">
      <PostDetail id={id} />
    </div>
  );
}
