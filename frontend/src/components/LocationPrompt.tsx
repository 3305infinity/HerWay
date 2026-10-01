'use client';

import React, { useEffect, useState } from 'react';
import { ALL_INDIAN_REGIONS, composeLocation, extractPinCode } from '@/lib/india';

/**
 * Asks the user where they are, so HerWay can find nearby services.
 *
 * HerWay never assumes a location. Without one, local search is skipped and
 * the user is told so — rather than being shown results for some default city.
 */
export default function LocationPrompt({
  isOpen,
  currentLocation,
  onClose,
  onSave,
}: {
  isOpen: boolean;
  currentLocation?: string | null;
  onClose: () => void;
  onSave: (location: string) => Promise<void> | void;
}) {
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [pin, setPin] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setError(null);
    // Pre-fill from whatever we already know.
    if (currentLocation) {
      const detectedPin = extractPinCode(currentLocation);
      if (detectedPin) setPin(detectedPin);
      const matchedState = ALL_INDIAN_REGIONS.find((r) =>
        currentLocation.toLowerCase().includes(r.toLowerCase()),
      );
      if (matchedState) setState(matchedState);
      const firstPart = currentLocation.split(',')[0]?.trim();
      if (firstPart && firstPart !== matchedState && firstPart !== detectedPin) {
        setCity(firstPart);
      }
    }
  }, [isOpen, currentLocation]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const location = composeLocation({ city, state, pin });
    if (!location) {
      setError('Please enter at least a city or choose a state.');
      return;
    }
    if (pin && !/^[1-9]\d{5}$/.test(pin.trim())) {
      setError('An Indian PIN code is 6 digits, for example 110001.');
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      await onSave(location);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Set your location"
    >
      <div className="bg-card border border-border rounded-xl max-w-md w-full shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold text-foreground">Where are you?</h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <p className="text-xs text-muted-foreground leading-relaxed">
            This helps HerWay find One Stop Centres, women police stations and legal aid near
            you. A district or city is enough — you do not need to give an address.
          </p>

          <div className="space-y-1.5">
            <label htmlFor="loc-city" className="text-xs font-medium text-muted-foreground">
              City or district
            </label>
            <input
              id="loc-city"
              type="text"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="e.g. Nagpur"
              autoComplete="address-level2"
              className="w-full px-3.5 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="loc-state" className="text-xs font-medium text-muted-foreground">
              State or Union Territory
            </label>
            <select
              id="loc-state"
              value={state}
              onChange={(e) => setState(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
            >
              <option value="">Select…</option>
              {ALL_INDIAN_REGIONS.map((region) => (
                <option key={region} value={region}>
                  {region}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="loc-pin" className="text-xs font-medium text-muted-foreground">
              PIN code (optional)
            </label>
            <input
              id="loc-pin"
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
              placeholder="e.g. 440001"
              autoComplete="postal-code"
              className="w-full px-3.5 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-colors"
            />
          </div>

          {error && (
            <p role="alert" className="text-xs text-rose-700 dark:text-rose-400">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg border border-border text-foreground text-sm font-medium hover:bg-muted transition-colors"
            >
              Not now
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {isSaving ? 'Saving…' : 'Save location'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
