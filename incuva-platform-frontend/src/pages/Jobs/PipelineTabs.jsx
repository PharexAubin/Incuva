// src/pages/Jobs/PipelineTabs.jsx
import React from "react";
import { PIPELINE_TABS } from "./pipeline";

/**
 * Barre d'onglets du pipeline de recrutement, avec un compteur par onglet.
 * Le filtrage se fait en mémoire dans JobsDetails : changer d'onglet ne recharge rien.
 */
export default function PipelineTabs({ counts, activeTab, onChange }) {
  return (
    <div role="tablist" aria-label="Pipeline de recrutement" className="flex gap-1 overflow-x-auto px-6 pt-4 border-b border-gray-100">
      {PIPELINE_TABS.map((tab) => {
        const active = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={`flex-shrink-0 flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              active
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
            }`}
          >
            {tab.label}
            <span
              className={`min-w-[1.5rem] px-2 py-0.5 rounded-full text-xs font-semibold text-center ${
                active ? "bg-blue-600 text-white" : counts[tab.id] > 0 ? "bg-gray-200 text-gray-700" : "bg-gray-100 text-gray-400"
              }`}
            >
              {counts[tab.id]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
