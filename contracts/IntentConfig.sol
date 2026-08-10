// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Tiny Base Sepolia demo contract for ProofPilot Intent Assurance.
contract IntentConfig {
    address public immutable controller;
    uint256 public threshold;
    bool public paused;

    event ThresholdChanged(uint256 oldValue, uint256 newValue);
    event PauseChanged(bool paused);

    error Unauthorized();
    error InvalidController();

    constructor(uint256 initialThreshold, address controller_) {
        if (controller_ == address(0)) revert InvalidController();
        controller = controller_;
        threshold = initialThreshold;
    }

    modifier onlyController() {
        if (msg.sender != controller) revert Unauthorized();
        _;
    }

    function setThreshold(uint256 newThreshold) external onlyController {
        uint256 oldValue = threshold;
        threshold = newThreshold;
        emit ThresholdChanged(oldValue, newThreshold);
    }

    function setPaused(bool newPaused) external onlyController {
        paused = newPaused;
        emit PauseChanged(newPaused);
    }
}

