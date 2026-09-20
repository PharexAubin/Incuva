import React from 'react';
import { X, FileText } from 'lucide-react';

export default function CvPreviewModal({ cvUrl, cvName, onClose, loading = false, error = "" }) {
  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-75 z-50 flex justify-center items-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-3xl shadow-2xl w-full max-w-4xl h-5/6 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header de la Modale */}
        <div className="flex justify-between items-center p-5 border-b border-gray-200 bg-gray-50">
          <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <FileText className="w-6 h-6 text-indigo-600" />
            Prévisualisation : {cvName || "Curriculum Vitæ"}
          </h3>
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-red-100 text-red-500 transition"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Contenu de l'Aperçu (Iframe) */}
        <div className="flex-1">
          {loading && (
            <div className="p-8 text-center text-gray-500">Chargement du CV...</div>
          )}
          {error && (
            <div className="p-8 text-center text-red-600">{error}</div>
          )}
          {cvUrl && (
            <iframe
              src={cvUrl}
              title={`Aperçu du CV - ${cvName}`}
              className="w-full h-full border-0"
              frameBorder="0"
            />
          )}
        </div>
      </div>
    </div>
  );
};