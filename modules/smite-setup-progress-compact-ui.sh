#!/bin/bash

# U-OPTI - Smite Private Setup Progress compact menu
# Presentation override used by the clean-install Wizard prototype.
#
# The 10-step progress list is the menu. Prefix a step number with a dot to
# open its read-only details page (for example: .2). Runtime verification is
# collected silently before each render; no separate details list is needed.

show_smite_setup_progress_menu() {
    local choice step

    if ! smite_setup_ui_require_core; then
        clear
        echo "ERROR: Smite setup progress core module is not loaded."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    while true; do
        # smite_setup_progress_render -> collect() performs the verification
        # silently before drawing the current progress state.
        smite_setup_progress_render
        echo
        echo "--------------------------------------"
        echo "1-10   Open step / available actions"
        echo ".1-.10 Show details for a step (example: .2)"
        echo "n      Show next recommended step"
        echo "r      Refresh progress"
        echo "0      Back"
        echo "--------------------------------------"
        echo
        read -rp "Selection: " choice

        case "$choice" in
            0) break ;;
            n|N) smite_setup_progress_show_next ;;
            r|R) : ;;
            1|2|3|4|5|6|7|8|9|10)
                smite_setup_ui_open_step "$choice"
                ;;
            .1|.2|.3|.4|.5|.6|.7|.8|.9|.10)
                step="${choice#.}"
                smite_setup_ui_show_step_details "$step"
                ;;
            *)
                echo
                echo "Invalid selection! Use 1-10, .1-.10, n, r, or 0."
                sleep 2
                ;;
        esac
    done
}
