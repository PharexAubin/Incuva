// frontend/src/pages/profil/composant/SectionCV.jsx
import React, { useState } from 'react';
import { FileText, Upload, Check, AlertCircle } from 'lucide-react';
import { getCvViewUrl } from '../../../services/auth';

const SectionCV = ({ profile, formData, isEditing, cvInputRef, handleCVUpload, uploadingCv }) => {
  const [openingCv, setOpeningCv] = useState(false);
  const [viewError, setViewError] = useState('');

  const handleViewCV = async () => {
    setOpeningCv(true);
    setViewError('');
    // Ouvrir l'onglet tout de suite (clic utilisateur) pour ne pas être bloqué par le navigateur
    const tab = window.open('', '_blank');
    try {
      const res = await getCvViewUrl();
      if (!res.success) throw new Error(res.error || "Impossible d'ouvrir le CV");
      if (tab) tab.location.href = res.url;
      else window.location.href = res.url;
    } catch (err) {
      if (tab) tab.close();
      setViewError(err.message || "Impossible d'ouvrir le CV");
    } finally {
      setOpeningCv(false);
    }
  };

  return (
    <div className="bg-white rounded-3xl shadow-xl p-8">
      <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
        <FileText className="w-7 h-7 text-purple-600" />
        Curriculum Vitæ
      </h2>
      {isEditing ? (
        <div>
          <input ref={cvInputRef} type="file" accept=".pdf,.doc,.docx" onChange={handleCVUpload} className="hidden" />
          <button
            onClick={() => cvInputRef.current?.click()}
            disabled={uploadingCv}
            className="flex items-center gap-3 px-6 py-4 bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-2xl hover:shadow-xl transition disabled:opacity-70">
            {uploadingCv ? (
                <><Upload className="w-5 h-5 animate-spin" /> Upload en cours...</>
            ) : (
                <><Upload className="w-5 h-5" /> {formData.cvName ? 'Changer mon CV' : 'Téléverser mon CV'}</>
            )}
          </button>
          {formData.cvName && (
            <p className={`mt-4 flex items-center gap-2 ${uploadingCv ? 'text-yellow-600' : 'text-green-600'}`}>
              {uploadingCv ? <AlertCircle className="w-5 h-5" /> : <Check className="w-5 h-5" />}
               Fichier actuel : {formData.cvName}
            </p>
          )}
        </div>
      ) : profile?.cvUrl ? (
        <div>
          <button type="button" onClick={handleViewCV} disabled={openingCv}
            className="inline-flex items-center gap-3 text-purple-600 hover:text-purple-800 font-bold transition disabled:opacity-70">
            <FileText className="w-6 h-6" /> {openingCv ? 'Ouverture...' : `Voir mon CV (${profile.cvName})`}
          </button>
          {viewError && <p className="mt-2 text-sm text-red-600">{viewError}</p>}
        </div>
      ) : (
        <p className="text-gray-500 italic">Aucun CV téléversé</p>
      )}
    </div>
  );
};

export default SectionCV;