// src/components/PinnedTestsBar.jsx
import React from "react";
import { Link } from "react-router-dom";
import { ClipboardList } from "lucide-react";

/**
 * Barre épinglée sous l'en-tête de la conversation (hors de la zone qui défile) : les tests techniques
 * restent visibles, même après de nombreux échanges.
 * - Candidat : les tests à passer, avec un accès direct.
 * - Entreprise : les tests envoyés avec leur état (en attente, ou résultat).
 */
export default function PinnedTestsBar({ assignments = [], currentAccountType }) {
  const isCompany = currentAccountType === "company";
  const visible = isCompany
    ? assignments
    : assignments.filter((assignment) => assignment.status === "assigned");

  if (visible.length === 0) return null;

  return (
    <div className="relative z-10 bg-amber-50/90 backdrop-blur border-b border-amber-200">
      <div className="max-w-4xl mx-auto px-4 py-2 space-y-1">
        {visible.map((assignment) => {
          const submitted = assignment.status === "submitted";
          const result = assignment.result;
          return (
            <div key={assignment.id} className="flex items-center justify-between gap-3 text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <ClipboardList className="w-4 h-4 text-amber-600 flex-shrink-0" />
                <span className="truncate text-amber-900">
                  <span className="font-semibold">
                    {isCompany ? "Test envoyé" : "Test à passer"}
                  </span>{" "}
                  — {assignment.test_title}
                </span>
              </div>
              {isCompany ? (
                <span className="flex-shrink-0 text-xs font-medium text-amber-800">
                  {!submitted
                    ? "En attente du candidat"
                    : result?.awaiting_grading
                      ? "À corriger"
                      : result
                        ? `${result.score}/${result.max_score} (${Math.round(result.percentage)} %)`
                        : "Soumis"}
                </span>
              ) : (
                <Link
                  to={`/technical-test/${assignment.test_id}`}
                  className="flex-shrink-0 px-3 py-1 bg-amber-500 text-white rounded-lg text-xs font-semibold hover:bg-amber-600 transition-colors"
                >
                  Passer le test
                </Link>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
