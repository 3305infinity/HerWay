import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from './ui/button';
import { ShareIcon, Sparkles } from 'lucide-react';
import Image from 'next/image';
import axios from 'axios';

interface ShareProps {
  imageURL: string;
  resText: string;
  setShared: (shared: boolean) => void;
}

function Share({ imageURL, resText, setShared }: ShareProps) {
  const router = useRouter();
  const [encodedImage, setEncodedImage] = React.useState<string>('');
  const [isSavingCase, setIsSavingCase] = useState(false);
  const handleCommonFunction = async () => {
    // decode api - img as url (main branch)
    // decompose - generated text
    // save to db
    console.log('resText: ', resText);
    const encodeImage = await axios.post('/api/decompose', {
      resImage: imageURL,
    });
    setEncodedImage(encodeImage.data.encodedImage);
    const decomposeReq = await axios.post('/api/decompose', {
      resText: resText,
    });
    // add status(pending) to decomposeReq.data.decomposed
    const data = {
      ...decomposeReq.data.decomposed,
      status: 'pending',
    };
    const saveReq = await axios.post('/api/save', data);
    if (saveReq.status !== 200) {
      console.log('Failed to save to DB');
    }
  };

  const handleShareTelegram = () => {
    const telegramShareUrl = `https://t.me/share/url?url=${encodeURIComponent(
      encodedImage
    )}`;
    window.open(telegramShareUrl, '_blank');

    handleCommonFunction();
    setShared(true);
  };

  const handleShareTwitter = () => {
    const twitterShareUrl = `https://twitter.com/intent/tweet?url=${encodeURIComponent(
      imageURL
    )}`;
    window.open(twitterShareUrl, '_blank');
    handleCommonFunction();
    setShared(true);
  };

  const handleSaveToCase = async () => {
    setIsSavingCase(true);
    try {
      await handleCommonFunction();
      const res = await axios.post('/api/v2/cases', {
        user_id: 'anonymous',
        situation_text: resText,
        category: 'safety',
        title: `Discreet Report: ${resText.slice(0, 35)}`,
      });
      if (res.status === 200 || res.status === 201) {
        const newCase = res.data;
        const id = newCase.id || newCase._id;
        router.push(`/cases/${id}`);
      }
    } catch (e) {
      console.error('Failed to create case from discreet report:', e);
    } finally {
      setIsSavingCase(false);
    }
  };

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Adjusted Image size */}
      <div className="relative w-[500px] h-[500px]">
        <Image
          src={imageURL}
          alt="Generated Image"
          layout="fill"
          objectFit="cover"
          className="rounded-md"
        />
      </div>

      <div className="flex items-center gap-3 flex-wrap justify-center">
        <Button
          variant="default"
          className="flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
          onClick={handleSaveToCase}
          disabled={isSavingCase}
        >
          <Sparkles size={20} />
          <span>{isSavingCase ? 'Creating case…' : 'Save as Guided Safety Case'}</span>
        </Button>
        <Button
          variant="outline"
          className="flex items-center gap-2"
          onClick={handleShareTelegram}
        >
          <ShareIcon size={20} />
          Share on Telegram
        </Button>
        <Button
          variant="outline"
          className="flex items-center gap-2 bg-black text-white hover:bg-black/90 hover:text-white"
          onClick={handleShareTwitter}
        >
          <ShareIcon size={20} />
          Share on Twitter
        </Button>
        <Button
          variant="outline"
          className="flex items-center gap-2 bg-gradient-to-r from-[#405DE6] to-[#5851DB] text-white"
        >
          <ShareIcon size={20} />
          Share on Instagram
        </Button>
      </div>
    </div>
  );
}

export default Share;
