'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { InputForm } from '@/components/InputForm';
import Share from '@/components/Share';
import { useClerk } from '@clerk/nextjs';
import HorizontalLinearStepper from '@/components/MultiStep';
import ImageGen from '@/components/ImageGen';
function Page() {
  const [resImage, setResImage] = useState<string | null>(null);
  const [resText, setText] = useState<string | null>(null);
  const [resTextGemma, setTextGemma] = useState<string | null>(null);
  const { user } = useClerk();
  const [activeStep, setActiveStep] = useState(0);
  const [shared, setShared] = useState(false);

  useEffect(() => {
    // Move to the next step when resImage is set
    if (resText && resTextGemma) {
      setActiveStep(1);
    }
  }, [resText, resTextGemma]);

  useEffect(() => {
    // Move to the next step when resImage is set
    if (resImage) {
      setActiveStep(2);
    }
  }, [resImage]);

  useEffect(() => {
    if (shared) {
      setActiveStep(4);
    }
  }, [shared]);

  const stepContent = [
    <InputForm key="step1" setText={setText} setTextGemma={setTextGemma} />, // Step 1
    <ImageGen
      key="step2"
      text={resText || ''}
      setResImage={setResImage}
      textGemma={resTextGemma || ''}
    />, // Step 2
    <Share
      key="step3"
      imageURL={resImage || ''}
      setShared={setShared}
      resText={resText || ''}
    />, // Step 2
  ];

  const [allowAnonymous, setAllowAnonymous] = useState(false);

  if (!user && !allowAnonymous) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-3.5rem)] p-4">
        <div className="text-center max-w-sm space-y-4 p-8 border border-border rounded-2xl bg-card shadow-sm">
          <h1 className="text-xl font-semibold text-foreground">Discreet Message & Post</h1>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Signing in allows you to manage your posts and reports. If you are in immediate danger or prefer complete discretion, you can also proceed anonymously.
          </p>
          <div className="space-y-2 pt-2">
            <button
              type="button"
              onClick={() => setAllowAnonymous(true)}
              className="w-full py-2.5 bg-primary text-primary-foreground text-sm font-medium rounded-xl hover:bg-primary/90 transition-colors"
            >
              Continue Anonymously
            </button>
            <Link
              href="/sign-in"
              className="block w-full py-2.5 border border-border text-foreground text-sm font-medium rounded-xl hover:bg-muted transition-colors text-center"
            >
              Sign in with an account
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center">
      <HorizontalLinearStepper
        activeStep={activeStep}
        stepContent={stepContent}
      />
    </div>
  );
}

export default Page;
