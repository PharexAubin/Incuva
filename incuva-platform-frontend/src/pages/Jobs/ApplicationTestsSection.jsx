// src/pages/Jobs/ApplicationTestsSection.jsx
import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { ClipboardList, Send, CheckCircle, Clock, Loader2, MessageCircle, Eye, X } from "lucide-react";
import {
  getApplicationTests,
  assignTechnicalTest,
  getAvailableTestsForJob,
  getTechnicalTest,
} from "../../services/technical";
import { startConversation } from "../../services/messaging";
import AttemptDetailsModal from "./Entreprises/TechnicalTest/components/AttemptDetailsModal.jsx";

/**
 * Section « Tests techniques » de la fiche de candidature (côté entreprise).
 *
 * Règle métier : un test ne peut être envoyé qu'à une candidature ACCEPTÉE. Le bouton est donc désactivé
 * tant que la candidature est en attente, et absent si elle est refusée ou retirée. Cette règle est aussi
 * contrôlée par le serveur (POST /api/technical-tests/assign) : masquer le bouton ne suffit pas à elle seule.
 */
export default function ApplicationTestsSection({ application, jobId }) {
  const navigate = useNavigate();
  const status = application.status;

  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [availableTests, setAvailableTests] = useState([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [sendingTestId, setSendingTestId] = useState(null);

  const [error, setError] = useState(null); // { message, code, testId }
  const [notice, setNotice] = useState(null); // { message, chatId }
  const [detail, setDetail] = useState(null); // { attempt, test }
  const [detailLoadingId, setDetailLoadingId] = useState(null);

  const loadAssignments = useCallback(async () => {
    setLoading(true);
    const res = await getApplicationTests(application.application_id);
    setAssignments(res.success ? res.data : []);
    setLoading(false);
  }, [application.application_id]);

  useEffect(() => {
    setPickerOpen(false);
    setError(null);
    setNotice(null);
    loadAssignments();
  }, [loadAssignments]);

  const openPicker = async () => {
    setPickerOpen(true);
    setError(null);
    setNotice(null);
    setPickerLoading(true);
    const res = await getAvailableTestsForJob(jobId);
    setAvailableTests(res.success ? res.data || [] : []);
    if (!res.success) setError({ message: res.error || "Impossible de charger les tests de l'offre" });
    setPickerLoading(false);
  };

  const sendTest = async (test) => {
    setError(null);
    setSendingTestId(test.id);
    const res = await assignTechnicalTest(application.application_id, test.id);
    setSendingTestId(null);

    if (res.success) {
      setPickerOpen(false);
      setNotice({ message: `Le test « ${test.title} » a été envoyé dans la conversation.`, chatId: res.data.chat_id });
      loadAssignments();
    } else {
      setError({ message: res.error, code: res.code, test });
    }
  };

  // Pas de conversation : on la crée avec l'action « Contacter » existante, puis on renvoie le test
  const contactThenSend = async () => {
    const test = error.test;
    setSendingTestId(test.id);
    const conversation = await startConversation(application.candidate_id, jobId);
    if (!conversation.success) {
      setSendingTestId(null);
      setError({ message: conversation.error || "Impossible de démarrer la conversation", test });
      return;
    }
    await sendTest(test);
  };

  const openDetail = async (assignment) => {
    setDetailLoadingId(assignment.id);
    const res = await getTechnicalTest(assignment.test_id);
    setDetailLoadingId(null);
    if (res.success) setDetail({ attempt: assignment.attempt, test: res.data });
    else setError({ message: res.error || "Impossible de charger le détail du test" });
  };

  const alreadySent = new Set(assignments.map((a) => a.test_id));
  const selectable = availableTests.filter((test) => !alreadySent.has(test.id));
  const canSend = status === "accepted";
  const canSeeSendButton = status === "accepted" || status === "pending";

  // Rien à montrer pour une candidature refusée/retirée sans aucun test
  if (!canSeeSendButton && !loading && assignments.length === 0) return null;

  return (
    <div>
      <h4 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <ClipboardList className="w-4 h-4 text-blue-600" />
        Tests techniques
      </h4>

      {/* Tests déjà envoyés et leur résultat */}
      {loading ? (
        <p className="text-sm text-gray-500 flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Chargement...
        </p>
      ) : (
        assignments.length > 0 && (
          <div className="space-y-2 mb-4">
            {assignments.map((assignment) => {
              const submitted = assignment.status === "submitted";
              const result = assignment.result;
              return (
                <div
                  key={assignment.id}
                  className="flex items-center justify-between gap-3 p-3 bg-gray-50 border border-gray-200 rounded-xl"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 text-sm truncate">{assignment.test_title}</p>
                    {!submitted ? (
                      <p className="text-xs text-amber-700 flex items-center gap-1 mt-0.5">
                        <Clock className="w-3 h-3" /> En attente du candidat
                      </p>
                    ) : result ? (
                      <p className={`text-xs flex items-center gap-1 mt-0.5 ${result.passed ? "text-green-700" : "text-red-700"}`}>
                        <CheckCircle className="w-3 h-3" />
                        {result.score}/{result.max_score} ({Math.round(result.percentage)} %) —{" "}
                        {result.passed ? "réussi" : "non réussi"}
                      </p>
                    ) : (
                      <p className="text-xs text-gray-600 mt-0.5">Soumis</p>
                    )}
                  </div>
                  {submitted && assignment.attempt && (
                    <button
                      onClick={() => openDetail(assignment)}
                      disabled={detailLoadingId === assignment.id}
                      className="flex-shrink-0 px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors flex items-center gap-1 disabled:opacity-60"
                    >
                      {detailLoadingId === assignment.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Eye className="w-3 h-3" />
                      )}
                      Voir le détail
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )
      )}

      {notice && (
        <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded-xl text-sm text-green-800 flex items-center justify-between gap-3">
          <span>{notice.message}</span>
          {notice.chatId && (
            <button
              onClick={() => navigate(`/messaging/conversation/${notice.chatId}`)}
              className="flex-shrink-0 font-medium underline hover:text-green-900"
            >
              Ouvrir la conversation
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <p>{error.message}</p>
          {error.code === "no_conversation" && (
            <button
              onClick={contactThenSend}
              disabled={sendingTestId === error.test?.id}
              className="mt-2 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-60 flex items-center gap-1.5"
            >
              {sendingTestId === error.test?.id ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <MessageCircle className="w-3 h-3" />
              )}
              Contacter d'abord, puis envoyer le test
            </button>
          )}
        </div>
      )}

      {/* Bouton d'envoi : actif seulement pour une candidature acceptée */}
      {canSeeSendButton && (
        <>
          <button
            onClick={openPicker}
            disabled={!canSend || pickerOpen}
            title={canSend ? "" : "Acceptez d'abord la candidature"}
            className="px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-xl font-medium shadow-sm flex items-center gap-2 transition-all hover:from-blue-700 hover:to-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:from-blue-600"
          >
            <Send className="w-4 h-4" />
            Envoyer un test technique
          </button>
          {!canSend && (
            <p className="text-xs text-gray-500 mt-2">
              Acceptez d'abord la candidature pour pouvoir envoyer un test technique au candidat.
            </p>
          )}
        </>
      )}

      {/* Choix du test */}
      {pickerOpen && canSend && (
        <div className="mt-3 p-4 border-2 border-blue-100 rounded-xl bg-blue-50/40">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-gray-900">Choisissez le test à envoyer</p>
            <button onClick={() => setPickerOpen(false)} className="p-1 hover:bg-white rounded-lg text-gray-500">
              <X className="w-4 h-4" />
            </button>
          </div>
          {pickerLoading ? (
            <p className="text-sm text-gray-500 flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" /> Chargement des tests...
            </p>
          ) : selectable.length === 0 ? (
            <div className="text-sm text-gray-600">
              <p>
                {availableTests.length === 0
                  ? "Aucun test actif pour cette offre."
                  : "Tous les tests actifs de cette offre ont déjà été envoyés à ce candidat."}
              </p>
              <button
                onClick={() => navigate(`/jobs/${jobId}/technical-test`)}
                className="mt-2 text-blue-700 font-medium underline hover:text-blue-900"
              >
                Créer un test pour cette offre
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {selectable.map((test) => (
                <button
                  key={test.id}
                  onClick={() => sendTest(test)}
                  disabled={sendingTestId !== null}
                  className="w-full text-left p-3 bg-white border border-gray-200 rounded-xl hover:border-blue-400 hover:shadow-sm transition-all disabled:opacity-60 flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 text-sm truncate">{test.title}</p>
                    <p className="text-xs text-gray-500">
                      {test.questions?.length || 0} question{(test.questions?.length || 0) > 1 ? "s" : ""}
                      {test.duration ? ` • ${test.duration} min` : ""}
                    </p>
                  </div>
                  {sendingTestId === test.id ? (
                    <Loader2 className="w-4 h-4 animate-spin text-blue-600 flex-shrink-0" />
                  ) : (
                    <Send className="w-4 h-4 text-blue-600 flex-shrink-0" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {detail && (
        <AttemptDetailsModal attempt={detail.attempt} test={detail.test} onClose={() => setDetail(null)} />
      )}
    </div>
  );
}
