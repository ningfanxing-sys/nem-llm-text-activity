# Additional seeds and windowed activity calculations

The scripts call the frozen execution adapter with the same fitting parameters, training rows, feature order and scoring functions. The no-text fits at seeds 20260920 and 20260921 change only the random seed. The seven-day and 24-hour notice fits replace the cumulative activity columns with windowed counts; representation columns and training-only pruning retain their definitions.

Read-only matrix interfaces supply slices in memory without copying the full feature matrices. The equivalence records bind the shared inputs and parameters and record zero prediction differences for the four baseline fits. Forecasts, common keys and truth determine every daily loss and comparison in the portable verifier.
