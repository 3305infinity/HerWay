import React from 'react';

function Loading() {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center">
      <div className="text-center space-y-3">
        <div
          className="w-6 h-6 border-2 border-border border-t-primary rounded-full animate-spin mx-auto"
          aria-hidden="true"
        />
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    </div>
  );
}

export default Loading;
