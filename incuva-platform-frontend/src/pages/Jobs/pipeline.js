// src/pages/Jobs/pipeline.js
// Pipeline de recrutement : les 4 catégories + « Toutes », calculées à partir de `status` et `qualified`.
//
// La catégorie n'est jamais stockée : c'est un calcul sur la liste déjà chargée. Le backend reste seul
// à écrire `qualified` (test réussi ou qualification manuelle) ; ici on ne fait que lire.

// Ordre d'affichage des onglets ; « Toutes » est le 5e.
export const PIPELINE_TABS = [
  { id: 'new', label: 'Nouvelles candidatures', empty: "Aucune nouvelle candidature à traiter." },
  { id: 'retained', label: 'Candidatures retenues', empty: "Aucune candidature retenue en attente de qualification." },
  { id: 'qualified', label: 'Qualifiés', empty: "Aucun candidat qualifié pour le moment." },
  { id: 'refused', label: 'Refusés / Retirés', empty: "Aucune candidature refusée ou retirée." },
  { id: 'all', label: 'Toutes', empty: "Aucune candidature pour le moment." },
];

/**
 * Catégorie d'une candidature, ou null pour un statut inattendu (visible seulement dans « Toutes »).
 * - pending                       → new
 * - accepted, pas qualifié        → retained
 * - accepted et qualifié          → qualified (qualifié par un test réussi OU manuellement : même champ)
 * - rejected / withdrawn          → refused
 */
export function getPipelineCategory(application) {
  switch (application.status) {
    case 'pending':
      return 'new';
    case 'accepted':
      return application.qualified === true ? 'qualified' : 'retained';
    case 'rejected':
    case 'withdrawn':
      return 'refused';
    default:
      return null;
  }
}

/** Nombre de candidatures par onglet. `all` compte tout, y compris un éventuel statut inattendu. */
export function countByCategory(applications) {
  const counts = { new: 0, retained: 0, qualified: 0, refused: 0, all: applications.length };
  applications.forEach((application) => {
    const category = getPipelineCategory(application);
    if (category) counts[category] += 1;
  });
  return counts;
}

/** Candidatures à afficher pour l'onglet actif. */
export function filterByTab(applications, tabId) {
  if (tabId === 'all') return applications;
  return applications.filter((application) => getPipelineCategory(application) === tabId);
}

/** Onglet ouvert par défaut : le premier qui contient des candidatures, sinon « Toutes ». */
export function defaultTab(counts) {
  const firstWithCandidates = PIPELINE_TABS.find((tab) => tab.id !== 'all' && counts[tab.id] > 0);
  return firstWithCandidates ? firstWithCandidates.id : 'all';
}
