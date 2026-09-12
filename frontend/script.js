/**
 * WrapShield AI — Food Packaging Recommendation Assistant
 * Frontend Controller & Interaction Logic
 */

// Configuration & Backend Base URL determination
// If served from Flask directly (same origin) use "", otherwise fallback to http://127.0.0.1:5000
const API_BASE = (window.location.protocol.startsWith("http") && window.location.port === "5000")
  ? ""
  : "http://127.0.0.1:5000";

// LocalStorage Keys
const STORAGE_KEYS = {
  CHAT_HISTORY: "wrapshield_chat_history",
  FOOD_DETAILS: "wrapshield_food_details",
  LAST_RECOMMENDATION: "wrapshield_last_recommendation"
};

// Global State
let selectedImageFile = null;
let currentRecommendation = null;
let chatMessages = []; // Array of { sender: 'user' | 'assistant', text: string, time: string }

// DOM Elements
const elements = {
  // Status & Health
  statusBanner: document.getElementById("status-banner"),
  backendIndicator: document.getElementById("backend-indicator"),
  indicatorText: document.getElementById("indicator-text"),

  // Food Form
  foodForm: document.getElementById("food-form"),
  dropzone: document.getElementById("dropzone"),
  foodImageInput: document.getElementById("food-image"),
  uploadPrompt: document.getElementById("upload-prompt"),
  previewContainer: document.getElementById("preview-container"),
  imagePreview: document.getElementById("image-preview"),
  removeImageBtn: document.getElementById("remove-image-btn"),
  foodNameInput: document.getElementById("food-name"),
  shelfLifeInput: document.getElementById("shelf-life"),
  storageCondition: document.getElementById("storage-condition"),
  transportCondition: document.getElementById("transport-condition"),
  budgetPriority: document.getElementById("budget-priority"),
  analyzeBtn: document.getElementById("analyze-btn"),
  analyzeSpinner: document.getElementById("analyze-spinner"),

  // Recommendation Section
  recommendationPlaceholder: document.getElementById("recommendation-placeholder"),
  recommendationContent: document.getElementById("recommendation-content"),
  confidenceBadge: document.getElementById("confidence-badge"),
  recomFood: document.getElementById("recom-food"),
  recomShelfLife: document.getElementById("recom-shelf-life"),
  recomMaterial: document.getElementById("recom-material"),
  recomStructure: document.getElementById("recom-structure"),
  recomReason: document.getElementById("recom-reason"),
  barrierMoisture: document.getElementById("barrier-moisture"),
  barrierOxygen: document.getElementById("barrier-oxygen"),
  barrierLight: document.getElementById("barrier-light"),
  recomLowCost: document.getElementById("recom-low-cost"),
  recomSustainable: document.getElementById("recom-sustainable"),
  recomAssumptions: document.getElementById("recom-assumptions"),

  // Chat Section
  chatCard: document.querySelector(".chat-card"),
  chatMessagesContainer: document.getElementById("chat-messages-container"),
  chatEmptyHint: document.getElementById("chat-empty-hint"),
  chatTypingIndicator: document.getElementById("chat-typing-indicator"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatSendBtn: document.getElementById("chat-send-btn"),
  clearChatBtn: document.getElementById("clear-chat-btn"),
  clearRecomBtn: document.getElementById("clear-recom-btn")
};

// ==========================================
// Initialization & Storage Restoration
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  checkBackendHealth();
  restoreSavedState();
});

function setupEventListeners() {
  // Drag and drop & file upload
  elements.foodImageInput.addEventListener("change", handleFileSelect);
  elements.dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    elements.dropzone.classList.add("dragover");
  });
  elements.dropzone.addEventListener("dragleave", () => {
    elements.dropzone.classList.remove("dragover");
  });
  elements.dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    elements.dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processImageFile(e.dataTransfer.files[0]);
    }
  });
  elements.removeImageBtn.addEventListener("click", clearImagePreview);

  // Form Submission
  elements.foodForm.addEventListener("submit", handleFormSubmit);

  // Clear / Reset Recommendation
  if (elements.clearRecomBtn) {
    elements.clearRecomBtn.addEventListener("click", clearRecommendation);
  }

  // Chat Submission
  elements.chatForm.addEventListener("submit", handleChatSubmit);
  elements.clearChatBtn.addEventListener("click", clearChatHistory);
}

// ==========================================
// Backend Health Check
// ==========================================
async function checkBackendHealth() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (res.ok) {
      const data = await res.json();
      elements.backendIndicator.className = "backend-indicator connected";
      elements.indicatorText.textContent = data.gemini_api_configured ? "Backend Connected (Live AI)" : "Backend Connected (Demo Mode)";
    } else {
      setBackendDisconnected("Backend responded with error");
    }
  } catch (err) {
    setBackendDisconnected("Backend Offline — Run backend/app.py");
  }
}

function setBackendDisconnected(msg) {
  elements.backendIndicator.className = "backend-indicator disconnected";
  elements.indicatorText.textContent = msg;
}

// ==========================================
// Notification Banner
// ==========================================
function showBanner(message, type = "error", duration = 5000) {
  elements.statusBanner.className = `status-banner ${type}`;
  elements.statusBanner.textContent = message;
  elements.statusBanner.classList.remove("hidden");

  if (duration > 0) {
    setTimeout(() => {
      elements.statusBanner.classList.add("hidden");
    }, duration);
  }
}

// ==========================================
// Image Upload & Validation
// ==========================================
function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) {
    processImageFile(file);
  }
}

function processImageFile(file) {
  // Validate MIME type
  const allowedTypes = ["image/jpeg", "image/png", "image/webp"];
  if (!allowedTypes.includes(file.type)) {
    showBanner("Invalid file type. Please upload a JPG, PNG, or WEBP image.", "error");
    return;
  }

  // Validate File Size (Max 5MB)
  const maxSizeBytes = 5 * 1024 * 1024;
  if (file.size > maxSizeBytes) {
    showBanner("Image is too large! Maximum allowed size is 5MB.", "error");
    return;
  }

  selectedImageFile = file;

  // Render Image Preview
  const reader = new FileReader();
  reader.onload = (e) => {
    elements.imagePreview.src = e.target.result;
    elements.uploadPrompt.classList.add("hidden");
    elements.previewContainer.classList.remove("hidden");
  };
  reader.readAsDataURL(file);
}

function clearImagePreview(e) {
  if (e) e.stopPropagation();
  selectedImageFile = null;
  elements.foodImageInput.value = "";
  elements.imagePreview.src = "";
  elements.previewContainer.classList.add("hidden");
  elements.uploadPrompt.classList.remove("hidden");
}

// ==========================================
// Form Submit & Packaging Analysis
// ==========================================
async function handleFormSubmit(e) {
  e.preventDefault();

  const foodName = elements.foodNameInput.value.trim();
  const shelfLife = elements.shelfLifeInput.value.trim();
  const storage = elements.storageCondition.value;
  const transport = elements.transportCondition.value;
  const budget = elements.budgetPriority.value;

  // Validation: Must provide either food name or image
  if (!foodName && !selectedImageFile) {
    showBanner("Please enter a food name or upload a product photo to continue.", "error");
    elements.foodNameInput.focus();
    return;
  }

  // Prepare FormData for multipart submission
  const formData = new FormData();
  if (selectedImageFile) {
    formData.append("image", selectedImageFile);
  }
  formData.append("food_name", foodName);
  formData.append("shelf_life", shelfLife);
  formData.append("storage_condition", storage);
  formData.append("transport_condition", transport);
  formData.append("budget_priority", budget);

  // Set Loading State
  setLoadingState(true);

  try {
    const response = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      body: formData
    });

    const data = await response.json();

    if (!response.ok) {
      if (data.allow_manual_entry || (data.error && data.error.toLowerCase().includes("food name"))) {
        elements.foodNameInput.focus();
        elements.foodNameInput.classList.add("input-pulse");
        setTimeout(() => elements.foodNameInput.classList.remove("input-pulse"), 4000);
      }
      throw new Error(data.error || "Failed to analyze packaging requirements.");
    }

    // Successfully received recommendation
    currentRecommendation = data;
    renderRecommendation(data);

    // Save form details and recommendation to localStorage
    saveFormDataLocally({
      food_name: foodName,
      shelf_life: shelfLife,
      storage_condition: storage,
      transport_condition: transport,
      budget_priority: budget
    });
    localStorage.setItem(STORAGE_KEYS.LAST_RECOMMENDATION, JSON.stringify(data));

    showBanner("Recommendation generated successfully!", "success", 3000);

    // If AI provided follow-up questions, post an assistant chat prompt
    if (data.follow_up_questions && data.follow_up_questions.length > 0) {
      const questionsText = "I have analyzed your product! To fine-tune this further, could you answer:\n" +
        data.follow_up_questions.map(q => `• ${q}`).join("\n");
      appendChatMessage("assistant", questionsText);
    }

  } catch (error) {
    console.error("Analysis Error:", error);
    showBanner(error.message || "Could not connect to backend. Please ensure the Flask server is running.", "error");
  } finally {
    setLoadingState(false);
  }
}

function setLoadingState(isLoading) {
  elements.analyzeBtn.disabled = isLoading;
  if (isLoading) {
    elements.analyzeSpinner.classList.remove("hidden");
    elements.analyzeBtn.querySelector(".btn-text").textContent = "Analyzing with Gemini AI...";
  } else {
    elements.analyzeSpinner.classList.add("hidden");
    elements.analyzeBtn.querySelector(".btn-text").textContent = "⚡ Analyze Packaging";
  }
}

// ==========================================
// Recommendation View Renderer
// ==========================================
function renderRecommendation(data) {
  if (!data) return;

  // Identified Food & Shelf Life
  const foodName = data.identified_food || "Unspecified Food Product";
  elements.recomFood.textContent = foodName;
  elements.recomShelfLife.textContent = data.estimated_shelf_life || data.expected_shelf_life || "Standard Commercial Period";

  // Confidence Badge & Unidentified Food Handling
  if (foodName.toLowerCase().includes("could not be identified")) {
    elements.recomFood.style.color = "#d97706";
    elements.confidenceBadge.textContent = "Confidence: Low";
    elements.confidenceBadge.className = "badge badge-warning";
    showBanner("Food could not be identified confidently. Please enter the food name manually.", "warning", 6000);
    elements.foodNameInput.focus();
    elements.foodNameInput.classList.add("input-pulse");
    setTimeout(() => elements.foodNameInput.classList.remove("input-pulse"), 4000);
  } else {
    elements.recomFood.style.color = "";
    const confidence = data.confidence || "High";
    elements.confidenceBadge.textContent = `Confidence: ${confidence}`;
    elements.confidenceBadge.className = "badge " + (
      confidence.toLowerCase().includes("high") ? "badge-success" :
      confidence.toLowerCase().includes("medium") ? "badge-warning" : "badge-neutral"
    );
  }

  // Primary Material & Structure
  elements.recomMaterial.textContent = data.recommended_material || "Multi-layer Barrier Laminate";
  elements.recomStructure.textContent = data.packaging_structure || "Outer Layer + Core Barrier Layer + Heat-Sealing Layer";

  // Reason
  elements.recomReason.textContent = data.reason || "Recommended based on barrier and shelf-life requirements.";

  // Barrier Protection Indicators
  const barriers = data.barrier_needs || {};
  applyBarrierTag(elements.barrierMoisture, barriers.moisture_protection);
  applyBarrierTag(elements.barrierOxygen, barriers.oxygen_protection);
  applyBarrierTag(elements.barrierLight, barriers.light_protection);

  // Alternatives
  elements.recomLowCost.textContent = data.low_cost_alternative || "Co-extruded polyethylene pouch";
  elements.recomSustainable.textContent = data.sustainable_alternative || "Recyclable mono-PE or bio-based barrier pouch";

  // Assumptions & Limitations
  elements.recomAssumptions.innerHTML = "";
  const assumptions = data.assumptions || [
    "Product is prepared and packaged under sanitary conditions.",
    "Storage temperature is maintained within normal expected ranges.",
    "Shelf-life estimates require laboratory verification."
  ];

  assumptions.forEach(item => {
    const li = document.createElement("li");
    li.textContent = item;
    elements.recomAssumptions.appendChild(li);
  });

  // Switch display from placeholder to content
  elements.recommendationPlaceholder.classList.add("hidden");
  elements.recommendationContent.classList.remove("hidden");
  if (elements.clearRecomBtn) elements.clearRecomBtn.classList.remove("hidden");
}

function clearRecommendation() {
  currentRecommendation = null;
  localStorage.removeItem(STORAGE_KEYS.LAST_RECOMMENDATION);
  localStorage.removeItem(STORAGE_KEYS.FOOD_DETAILS);

  // Switch display back to clean placeholder
  elements.recommendationContent.classList.add("hidden");
  elements.recommendationPlaceholder.classList.remove("hidden");
  if (elements.clearRecomBtn) elements.clearRecomBtn.classList.add("hidden");

  // Reset confidence badge
  elements.confidenceBadge.textContent = "Awaiting Analysis";
  elements.confidenceBadge.className = "badge badge-neutral";

  // Reset form inputs & image preview
  elements.foodForm.reset();
  clearImagePreview();

  showBanner("Recommendation cleared. Ready for a new analysis.", "info", 2500);
}

function applyBarrierTag(element, level) {
  const lvl = (level || "Medium").toLowerCase();
  element.textContent = level || "Medium";
  element.className = "barrier-tag " + (
    lvl.includes("high") ? "tag-high" :
    lvl.includes("low") ? "tag-low" : "tag-medium"
  );
}

// ==========================================
// Interactive Consultation Chat
// ==========================================
async function handleChatSubmit(e) {
  e.preventDefault();
  const text = elements.chatInput.value.trim();

  if (!text) {
    showBanner("Please enter a question or message for the packaging assistant.", "error");
    return;
  }

  // Add user message to UI
  appendChatMessage("user", text);
  elements.chatInput.value = "";

  // Show typing indicator
  elements.chatTypingIndicator.classList.remove("hidden");
  elements.chatSendBtn.disabled = true;

  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        messages: chatMessages.slice(-6), // Send recent context
        current_food_details: currentRecommendation || {
          food_name: elements.foodNameInput.value.trim(),
          shelf_life: elements.shelfLifeInput.value.trim()
        }
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Failed to receive response from AI assistant.");
    }

    // Append AI response
    appendChatMessage("assistant", data.response || "I am unable to answer right now. Please try again.");

  } catch (error) {
    console.error("Chat Error:", error);
    appendChatMessage("assistant", "⚠️ Error: Unable to connect to the assistant. Please check if the backend server is running.");
  } finally {
    elements.chatTypingIndicator.classList.add("hidden");
    elements.chatSendBtn.disabled = false;
  }
}

function appendChatMessage(sender, text, timestamp = null, saveToStorage = true) {
  const time = timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const msgObj = { sender, text, timestamp: time };
  chatMessages.push(msgObj);

  // Hide empty state hint
  if (elements.chatEmptyHint) {
    elements.chatEmptyHint.classList.add("hidden");
  }

  // Create message bubble element
  const bubble = document.createElement("div");
  bubble.className = `message-bubble ${sender === "user" ? "message-user" : "message-ai"}`;

  // Format line breaks
  const formattedText = escapeHtml(text).replace(/\n/g, "<br>");
  bubble.innerHTML = `
    <div>${formattedText}</div>
    <span class="message-meta">${sender === "user" ? "You" : "WrapShield AI"} • ${time}</span>
  `;

  elements.chatMessagesContainer.appendChild(bubble);
  // Auto scroll to bottom
  elements.chatMessagesContainer.scrollTop = elements.chatMessagesContainer.scrollHeight;

  // Persist to localStorage only when requested
  if (saveToStorage) {
    localStorage.setItem(STORAGE_KEYS.CHAT_HISTORY, JSON.stringify(chatMessages));
  }
}

function clearChatHistory() {
  if (chatMessages.length === 0) return;
  chatMessages = [];
  localStorage.removeItem(STORAGE_KEYS.CHAT_HISTORY);

  // Clear container and show empty hint
  elements.chatMessagesContainer.innerHTML = "";
  if (elements.chatEmptyHint) {
    elements.chatEmptyHint.classList.remove("hidden");
    elements.chatMessagesContainer.appendChild(elements.chatEmptyHint);
  }
  showBanner("Chat history cleared.", "info", 2000);
}

// ==========================================
// LocalStorage Persistence Helpers
// ==========================================
function saveFormDataLocally(formData) {
  localStorage.setItem(STORAGE_KEYS.FOOD_DETAILS, JSON.stringify(formData));
}

function restoreSavedState() {
  // 1. Restore Form Fields
  try {
    const savedDetails = localStorage.getItem(STORAGE_KEYS.FOOD_DETAILS) || localStorage.getItem("packsmart_food_details");
    if (savedDetails) {
      const data = JSON.parse(savedDetails);
      if (data.food_name) elements.foodNameInput.value = data.food_name;
      if (data.shelf_life) elements.shelfLifeInput.value = data.shelf_life;
      if (data.storage_condition) elements.storageCondition.value = data.storage_condition;
      if (data.transport_condition) elements.transportCondition.value = data.transport_condition;
      if (data.budget_priority) elements.budgetPriority.value = data.budget_priority;
    }
  } catch (e) {
    console.warn("Could not restore saved food details", e);
  }

  // 2. Restore Last Recommendation
  try {
    const savedRecom = localStorage.getItem(STORAGE_KEYS.LAST_RECOMMENDATION) || localStorage.getItem("packsmart_last_recommendation");
    if (savedRecom) {
      currentRecommendation = JSON.parse(savedRecom);
      renderRecommendation(currentRecommendation);
    }
  } catch (e) {
    console.warn("Could not restore last recommendation", e);
  }

  // 3. Restore Chat History
  try {
    const savedChat = localStorage.getItem(STORAGE_KEYS.CHAT_HISTORY) || localStorage.getItem("packsmart_chat_history");
    if (savedChat) {
      const history = JSON.parse(savedChat);
      if (Array.isArray(history) && history.length > 0) {
        chatMessages = [];
        history.forEach(msg => {
          if (msg && msg.text) {
            appendChatMessage(msg.sender || "assistant", msg.text, msg.timestamp || null, false);
          }
        });
      }
    }
  } catch (e) {
    console.warn("Could not restore chat history", e);
  }
}

// Security helper
function escapeHtml(string) {
  const div = document.createElement("div");
  div.innerText = string;
  return div.innerHTML;
}
