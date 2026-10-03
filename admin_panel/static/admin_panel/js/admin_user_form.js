document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      button.setAttribute("aria-pressed", String(reveal));
      button.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
      const icon = button.querySelector("i");
      if (icon) {
        icon.classList.toggle("bi-eye", !reveal);
        icon.classList.toggle("bi-eye-slash", reveal);
      }
    });
  });

  const form = document.getElementById("admin-user-form");
  if (!form) return;
  const password = form.querySelector("[data-password-field]");
  const confirmation = form.querySelector("[data-confirm-password]");
  if (password && confirmation) {
    const validateMatch = () => {
      if (confirmation.value && password.value !== confirmation.value) {
        confirmation.setCustomValidity("The passwords do not match.");
      } else {
        confirmation.setCustomValidity("");
      }
    };
    password.addEventListener("input", validateMatch);
    confirmation.addEventListener("input", validateMatch);
    form.addEventListener("submit", validateMatch);
  }
});
