import React, { useState } from 'react';
import { FileText } from 'lucide-react';
import { SectionHeader } from './Helpers';
import { getTalentCvUrl } from '../../../../services/hr';

export default function SectionCV({ cvUrl, cvName, talentId, setShowCvModal }) {
  const [downloadError, setDownloadError] = useState('');
  if (!cvUrl) return null;

  // Lien temporaire (le bucket S3 n'est pas public) ouvert dans un nouvel onglet
  const handleDownload = async () => {
    setDownloadError('');
    const tab = window.open('', '_blank');
    const res = await getTalentCvUrl(talentId);
    if (res.success) {
      if (tab) tab.location.href = res.url;
      else window.location.href = res.url;
    } else {
      if (tab) tab.close();
      setDownloadError(res.error || "Impossible d'ouvrir le CV");
    }
  };

  return (
    <div className="bg-white rounded-3xl shadow-xl p-8 border border-gray-100">
      <SectionHeader icon={FileText} title="Curriculum Vitæ" />

      {/* 1. Bouton "Prévisualiser" */}
      <button
        onClick={() => setShowCvModal(true)}
        className="inline-flex items-center gap-3 px-6 py-4 bg-indigo-600 text-white rounded-2xl font-bold hover:bg-indigo-700 shadow-lg transition transform hover:-translate-y-0.5"
      >
        <FileText className="w-6 h-6" />
        Prévisualiser le CV
      </button>

      {/* 2. Bouton "Télécharger" (Optionnel) */}
      <button
        type="button"
        onClick={handleDownload}
        className="ml-4 inline-flex items-center gap-2 text-indigo-600 font-semibold hover:underline"
      >
        Télécharger
      </button>
      {downloadError && <p className="mt-3 text-sm text-red-600">{downloadError}</p>}
    </div>
  );
}