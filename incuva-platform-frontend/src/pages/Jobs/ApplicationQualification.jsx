// src/pages/Jobs/ApplicationQualification.jsx
import React, { useState } from "react";
import { BadgeCheck, Loader2 } from "lucide-react";
import { setApplicationQualification } from "../../services/jobs";

const SOURCE_LABELS = {
  test: "par un test technique réussi",
  manual: "manuellement",
};

/**
 * Qualification d'un candidat sur sa fiche de candidature.
 *
 * Visible seulement pour une candidature ACCEPTÉE. Cette règle est aussi contrôlée par le serveur
 * (POST /jobs/application/<id>/qualify et /unqualify) : masquer le bouton ne suffit pas à elle seule.
 * Un test technique réussi qualifie automatiquement ; le bouton sert aux offres sans test
 * (qualification sur entretien).
 */
export default function ApplicationQualification({ application, onChange }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (application.status !== "accepted") return null;
  const qualified = application.qualified === true;

  const change = async (qualify) => {
    if (!qualify && !window.confirm("Retirer la qualification de ce candidat ?")) return;
    setSaving(true);
    setError("");
    const res = await setApplicationQualification(application.application_id, qualify);
    setSaving(false);
    if (res.success) onChange(application.application_id, qualify);
    else setError(res.error);
  };

  const qualifiedAt = application.qualified_at ? new Date(application.qualified_at) : null;
  const qualifiedOn = qualifiedAt && !isNaN(qualifiedAt) ? qualifiedAt.toLocaleDateString("fr-FR") : null;

  return (
    <div>
      <h4 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <BadgeCheck className="w-4 h-4 text-emerald-600" />
        Qualification
      </h4>

      {qualified ? (
        <div className="flex items-center justify-between gap-3 p-3 bg-emerald-50 border border-emerald-200 rounded-xl">
          <div className="min-w-0">
            <p className="font-medium text-emerald-800 text-sm">Candidat qualifié</p>
            <p className="text-xs text-emerald-700 mt-0.5">
              {SOURCE_LABELS[application.qualified_source] ? `Qualifié ${SOURCE_LABELS[application.qualified_source]}` : "Qualifié"}
              {qualifiedOn ? ` le ${qualifiedOn}` : ""}
            </p>
          </div>
          <button
            onClick={() => change(false)}
            disabled={saving}
            className="flex-shrink-0 px-3 py-1.5 text-xs font-medium text-emerald-800 bg-white border border-emerald-300 rounded-lg hover:bg-emerald-100 transition-colors disabled:opacity-60 flex items-center gap-1"
          >
            {saving && <Loader2 className="w-3 h-3 animate-spin" />}
            Retirer la qualification
          </button>
        </div>
      ) : (
        <div>
          <button
            onClick={() => change(true)}
            disabled={saving}
            className="px-5 py-3 bg-gradient-to-r from-emerald-500 to-green-600 text-white rounded-xl font-medium shadow-sm flex items-center gap-2 transition-all hover:from-emerald-600 hover:to-green-700 disabled:opacity-60"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <BadgeCheck className="w-4 h-4" />}
            Qualifier ce candidat
          </button>
          <p className="text-xs text-gray-500 mt-2">
            Pour une offre sans test technique, par exemple après un entretien. Un test technique réussi qualifie
            automatiquement le candidat.
          </p>
        </div>
      )}

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
