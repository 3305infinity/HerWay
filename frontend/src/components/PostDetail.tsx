'use client';
import { cleanText, fetchCityName } from '@/lib/utils';
import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button } from './ui/button';
import {
  CircleX,
  CalendarDays,
  FileUser,
  PersonStanding,
  MapPin,
  TrendingUp,
  Loader2,
  Check,
  Sparkles,
  ArrowLeft,
} from 'lucide-react';
import CustomTimeline from './Timeline';
import toast from 'react-hot-toast';
import { ErrorState } from './States';
import { apiGet, apiPost } from '@/lib/api';
import type { CaseRecord } from '@/lib/types';

interface Post {
  _id: string;
  Name: string;
  Location: string;
  'Preferred way of contact': string;
  'Contact info': string;
  'Frequency of domestic violence': string;
  'Relationship with perpetrator': string;
  'Severity of domestic violence': string;
  'Nature of domestic violence': string;
  'Impact on children': string;
  'Culprit details': string;
  'Other info': string;
  status: string;
}

function PostDetail({ id }: { id: string }) {
  const router = useRouter();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [city, setCity] = useState<string | null>(null);
  const [isCreatingCase, setIsCreatingCase] = useState(false);

  const fetchPostById = React.useCallback(async () => {
    setError(null);
    const result = await apiGet<Post>(`/api/postbyid/${id}`);
    if (result.ok) {
      setPost(result.data);
    } else {
      setError(result.error.message);
    }
  }, [id]);

  useEffect(() => {
    void fetchPostById();
  }, [fetchPostById]);

  useEffect(() => {
    if (post) {
      const cleanLoc = cleanText(post.Location);
      const [lat, lng] = cleanLoc.split(',').map(Number);

      const fetchCity = async () => {
        try {
          const cityName = await fetchCityName(lat, lng);
          setCity(cityName);
        } catch (err) {
          console.error('Failed to fetch city name:', err);
        }
      };

      fetchCity();
    }
  }, [post]);

  if (error) {
    return (
      <div className="max-w-md mx-auto p-6">
        <ErrorState
          title="We could not load this post"
          message={error}
          onRetry={() => void fetchPostById()}
        >
          <Link
            href="/community"
            className="px-4 py-2 rounded-lg border border-border text-foreground text-sm font-medium hover:bg-muted transition-colors"
          >
            Back to community
          </Link>
        </ErrorState>
      </div>
    );
  }

  if (!post) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 size={24} className="animate-spin" />
      </div>
    );
  }
  const cleanLoc = cleanText(post.Location);
  const [lat, lng] = cleanLoc.split(',').map(Number);
  const mapKey = process.env.NEXT_PUBLIC_MAP_KEY;
  // Without a key, or without real coordinates, the embed renders a Google
  // error page. Show an honest placeholder instead.
  const mapUrl =
    mapKey && Number.isFinite(lat) && Number.isFinite(lng)
      ? `https://www.google.com/maps/embed/v1/place?key=${mapKey}&q=${lat},${lng}`
      : null;

  const handleCloseIssue = async (issueId: string) => {
    try {
      const response = await fetch('/api/closeIssue', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ issueId }),
      });

      if (!response.ok) {
        throw new Error('Failed to close issue');
      }

      // const data = await response.json();
      toast.success('Issue closed successfully');
      setPost((prevPost) =>
        prevPost ? { ...prevPost, status: 'closed' } : null
      );
    } catch (error) {
      console.error(error);
    }
  };

  const handleCreateCase = async () => {
    if (!post || isCreatingCase) return;
    setIsCreatingCase(true);
    try {
      const summary = [
        post['Nature of domestic violence'] ? `Nature: ${cleanText(post['Nature of domestic violence'])}` : '',
        post['Severity of domestic violence'] ? `Severity: ${cleanText(post['Severity of domestic violence'])}` : '',
        post['Frequency of domestic violence'] ? `Frequency: ${cleanText(post['Frequency of domestic violence'])}` : '',
        post['Culprit details'] ? `Culprit: ${cleanText(post['Culprit details'])}` : '',
        post['Other info'] ? `Additional Details: ${cleanText(post['Other info'])}` : '',
      ]
        .filter(Boolean)
        .join('. ');

      const result = await apiPost<CaseRecord>('/api/v2/cases', {
        situation_text: summary || 'Situation described in a community post.',
        category: 'domestic_violence',
        location: post.Location ? { display_name: cleanText(post.Location) } : null,
        title: 'Started from a community post',
      });

      if (result.ok) {
        toast.success('Your private case has been created.');
        router.push(`/cases/${result.data.id}`);
      } else {
        toast.error(result.error.message);
        setIsCreatingCase(false);
      }
    } catch {
      toast.error('We could not create the case. Please try again.');
      setIsCreatingCase(false);
    }
  };

  return (
    <div className="flex flex-col h-full max-w-6xl w-full mx-auto p-5 space-y-4">
      <div className="flex items-center justify-between">
        <Link
          href="/community"
          className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 transition-colors"
        >
          <ArrowLeft size={14} />
          <span>Back to Community</span>
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between w-full gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold">{post.Name}</h1>
          {post.Location && (
            <p className="text-xs text-muted-foreground mt-1">📍 {cleanText(post.Location)}</p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            onClick={handleCreateCase}
            disabled={isCreatingCase}
            className="flex items-center space-x-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Sparkles size={16} />
            <span>{isCreatingCase ? 'Creating case…' : 'Create Guided Case'}</span>
          </Button>

          {post.status === 'pending' && (
            <Button
              onClick={() => handleCloseIssue(post._id)}
              variant="outline"
              className="flex items-center space-x-2"
            >
              <CircleX size={16} />
              <span>Close Issue</span>
            </Button>
          )}
          {post.status === 'closed' && (
            <Button className="flex items-center space-x-2 bg-green-500 text-white hover:bg-green-600">
              <Check size={16} />
              <span>Issue Closed</span>
            </Button>
          )}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 mt-5">
        {/* Contact details are intentionally never rendered here. The
            community feed is public, and publishing a survivor's phone number
            or email would put them at risk. The API strips these fields too. */}
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">
              Frequency of domestic violence
            </h2>
            <CalendarDays className="text-gray-700" />
          </div>
          <p>{post['Frequency of domestic violence']}</p>
          <p>{post['Relationship with perpetrator']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">
              Nature of domestic violence
            </h2>
            <PersonStanding className="text-gray-700" />
          </div>
          <p>{post['Impact on children']}</p>
          <p>{post['Severity of domestic violence']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Culprit details</h2>
            <FileUser className="text-gray-700" />
          </div>
          <p>{post['Culprit details']}</p>
          <p>{post['Other info']}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Location</h2>
            <MapPin className="text-gray-700" />
          </div>
          <p>{post['Location']}</p>
          <p>{city}</p>
        </div>
        <div className="max-w-sm w-full rounded-md border flex flex-col gap-3 border-gray-400 p-3">
          <div className="flex items-center justify-between w-full gap-5">
            <h2 className="text-lg font-semibold">Current Status</h2>
            <TrendingUp className="text-gray-700" />
          </div>
          <p>{post.status}</p>
          <p>
            Resolve this issue by contacting the person and providing necessary
          </p>
        </div>
      </div>
      <div className="flex items-center w-full mt-5 gap-3">
        {mapUrl ? (
          <div className="rounded-md w-full p-1 border border-gray-400">
            <iframe
              title="Approximate location"
              width="100%"
              height="360"
              className="rounded-md border border-gray-300"
              style={{ border: 0 }}
              loading="lazy"
              allowFullScreen
              referrerPolicy="no-referrer-when-downgrade"
              src={mapUrl}
            />
          </div>
        ) : (
          <div className="rounded-md w-full h-[370px] p-4 border border-gray-400 flex items-center justify-center">
            <p className="text-sm text-muted-foreground text-center">
              No map is available for this post.
            </p>
          </div>
        )}
        <div className="rounded-md h-[370px] w-full p-4 border border-gray-400">
          <h1 className="text-center text-lg font-semibold mb-4">
            Recent Activities
          </h1>
          <CustomTimeline />
        </div>
      </div>
    </div>
  );
}

export default PostDetail;
