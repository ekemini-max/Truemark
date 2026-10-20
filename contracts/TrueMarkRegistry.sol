// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title TrueMarkRegistry
/// @notice Stores fingerprints (hashes) of academic records, never the records themselves.
///         A fingerprint is anchored once, can later be revoked, and can never be edited or removed.
///         Only wallets approved by the owner (the TrueMark backend) can write.
contract TrueMarkRegistry {
    error NotOwner();
    error NotOperator();
    error ZeroAddress();
    error ZeroHash();
    error AlreadyAnchored();
    error NotAnchored();
    error AlreadyRevoked();

    struct Anchor {
        bytes32 issuerRef; // pseudonymous reference to the issuing institution, never its name
        uint64 timestamp;  // block time when anchored; 0 means "never anchored"
        bool revoked;
    }

    address public owner;
    mapping(address => bool) public operators;
    mapping(bytes32 => Anchor) private anchors;

    event Anchored(bytes32 indexed recordHash, bytes32 indexed issuerRef, uint64 timestamp);
    event Revoked(bytes32 indexed recordHash, uint64 timestamp);
    event OperatorSet(address indexed operator, bool allowed);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyOperator() {
        if (!operators[msg.sender]) revert NotOperator();
        _;
    }

    constructor() {
        owner = msg.sender;
        operators[msg.sender] = true;
        emit OwnershipTransferred(address(0), msg.sender);
        emit OperatorSet(msg.sender, true);
    }

    function version() external pure returns (string memory) {
        return "1";
    }

    function setOperator(address operator, bool allowed) external onlyOwner {
        if (operator == address(0)) revert ZeroAddress();
        operators[operator] = allowed;
        emit OperatorSet(operator, allowed);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function anchor(bytes32 recordHash, bytes32 issuerRef) external onlyOperator {
        if (recordHash == bytes32(0)) revert ZeroHash();
        if (anchors[recordHash].timestamp != 0) revert AlreadyAnchored();
        uint64 ts = uint64(block.timestamp);
        anchors[recordHash] = Anchor(issuerRef, ts, false);
        emit Anchored(recordHash, issuerRef, ts);
    }

    function revoke(bytes32 recordHash) external onlyOperator {
        Anchor storage a = anchors[recordHash];
        if (a.timestamp == 0) revert NotAnchored();
        if (a.revoked) revert AlreadyRevoked();
        a.revoked = true;
        emit Revoked(recordHash, uint64(block.timestamp));
    }

    function check(bytes32 recordHash)
        external
        view
        returns (bool exists, bool revoked, bytes32 issuerRef, uint64 timestamp)
    {
        Anchor memory a = anchors[recordHash];
        return (a.timestamp != 0, a.revoked, a.issuerRef, a.timestamp);
    }
}
